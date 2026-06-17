# AIC Index 계산 - 설계 문서 완전 준수 버전
# 주요 수정: PI 가중치(0.4:0.3:0.3), TopicScore 복원, Spearman+CI, 메타데이터 강화

import os, re, json, argparse, datetime, warnings, time
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

# --------------------------
# Utilities
# --------------------------
def safe_text(x: str) -> str:
    """
    텍스트 전처리: 제어문자 제거 및 공백 정리
    - C0(0000-001F) + C1(007F-009F) 제어문자 제거
    - Zero-width 문자 제거
    - 다중 공백 정규화
    """
    if not isinstance(x, str):
        return ""
    # C0 + C1 제어문자
    x = re.sub(r"[\u0000-\u001F\u007F-\u009F]", " ", x)
    # Zero-width 문자 (U+200B 등)
    x = re.sub(r"[\u200B-\u200D\uFEFF]", "", x)
    # 공백 정리
    x = re.sub(r"\s+", " ", x).strip()
    return x

def tokenize_words(text: str):
    """
    영어/숫자/밑줄 기준 토큰화
    - 다국어 환경에서는 제한적이나 영어 중심 데이터에 적합
    """
    return re.findall(r"\b\w+\b", text)

def count_sentences(text: str) -> int:
    """
    문장 개수 카운트
    - 영어 종결부호(. ! ?) 기준
    - 한글 등 다국어는 추가 패턴 필요
    """
    parts = re.split(r"[.!?]+", text)
    return max(1, sum(1 for p in parts if p.strip()))

def minmax_norm(s: pd.Series, robust=False, percentile=(1, 99)) -> pd.Series:
    """
    Min-Max 정규화 (0-1)
    
    Args:
        robust: True면 percentile 기반 (이상치 견고)
        percentile: robust=True일 때 사용할 백분위수
    """
    s = s.astype(float)
    
    # NaN/Inf 필터링
    valid_mask = np.isfinite(s)
    if not valid_mask.any():
        return pd.Series([0.0]*len(s), index=s.index)
    
    if robust:
        mn, mx = np.percentile(s[valid_mask], percentile)
    else:
        mn, mx = s[valid_mask].min(), s[valid_mask].max()
    
    if pd.isna(mn) or pd.isna(mx) or mx - mn < 1e-10:
        return pd.Series([0.0]*len(s), index=s.index)
    
    normalized = (s - mn) / (mx - mn)
    normalized = np.clip(normalized, 0, 1)  # robust 모드에서 범위 초과 방지
    normalized = normalized.fillna(0.0)
    return normalized

DEFAULT_SINGLE_ANALYSIS_NORMALIZATION_SCALES = {
    "pi_depth_tokens": 100.0,
    "pi_avg_sent_len_raw": 20.0,
    "pi_ttr_raw": 0.5,
    "ui_raw": 0.2,
    "oi_raw": 0.125,
}

def saturating_ratio_norm(s: pd.Series, scale: float) -> pd.Series:
    """
    Saturating ratio 정규화 (0-1)

    단건 분석처럼 min-max 기준을 만들 수 없는 입력에서 사용한다.
    normalized = value / (value + scale)
    """
    s = s.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    safe_scale = float(scale) if scale and scale > 0 else 1.0
    normalized = s.clip(lower=0.0) / (s.clip(lower=0.0) + safe_scale)
    return normalized.clip(0.0, 1.0).fillna(0.0)

def normalize_metric(s: pd.Series, method: str = "minmax", scale: float | None = None) -> pd.Series:
    if method == "saturating_ratio":
        return saturating_ratio_norm(s, scale if scale is not None else 1.0)
    return minmax_norm(s)

def to_num(x):
    """안전한 숫자 변환"""
    try:
        return float(x)
    except:
        return np.nan

def ensure_cols(df: pd.DataFrame, cols):
    """필수 컬럼 존재 확인 및 생성"""
    for c in cols:
        if c not in df.columns:
            df[c] = "" if c != "rating" else np.nan
    return df

def validate_config(cfg):
    """
    설정 파일 검증
    - 필수 키 존재 확인
    - 기본값 보완
    """
    required = {
        "paths": ["input_csv", "out_dir"],
        "pi": ["critical_keywords", "weights"],
        "ui_oi": ["topic_score_alpha", "topic_score_beta"],
        "backend": ["prefer"],
        "weights": ["mode"],
        "misc": ["random_seed"]
    }
    
    for section, keys in required.items():
        if section not in cfg:
            raise ValueError(f"Config 섹션 누락: {section}")
        for key in keys:
            if key not in cfg[section]:
                raise ValueError(f"Config 키 누락: {section}.{key}")
    
    # 기본값 보완
    cfg["pi"].setdefault("weights", [0.4, 0.3, 0.3])
    cfg["ui_oi"].setdefault("topic_score_alpha", 1.0)
    cfg["ui_oi"].setdefault("topic_score_beta", 1.0)
    cfg["ui_oi"].setdefault("min_course_samples", 3)
    cfg["weights"].setdefault("min_ratings", 10)
    cfg["weights"].setdefault("clip_negative", True)
    cfg["weights"].setdefault("n_folds", 5)
    cfg["misc"].setdefault("export_text_columns", True)
    
    return cfg


# --------------------------
# Embedding Backend
# --------------------------
class EmbeddingBackend:
    """
    SBERT 또는 TF-IDF 임베딩 백엔드
    - 설정/메타데이터 추적 강화
    - 빈 코퍼스/행 방어 강화
    """
    def __init__(self, prefer="sbert", sbert_model="paraphrase-multilingual-mpnet-base-v2",
                 tfidf_ngram=(1, 2), tfidf_stopwords="english", 
                 sbert_batch_size=32, sbert_device=None, sbert_max_seq_length=None):
        self.prefer = prefer
        self.sbert_model_name = sbert_model
        self.tfidf_ngram = tfidf_ngram
        self.tfidf_stopwords = tfidf_stopwords
        self.sbert_batch_size = sbert_batch_size
        self.sbert_device = sbert_device
        self.sbert_max_seq_length = sbert_max_seq_length
        self.kind = None
        
        self.model = None
        self.vectorizer = None
        self.meta = {}  # 메타데이터 저장

    def fit(self, texts):
        """
        임베딩 모델 학습
        - 빈 코퍼스 방어: 최소 1개 유효 텍스트 보장
        - 실패 시 자동 폴백
        - 메타데이터 저장
        """
        # 빈 텍스트 필터링 및 플레이스홀더 추가
        texts = [t if isinstance(t, str) and t.strip() else "" for t in texts]
        if not any(t.strip() for t in texts):
            texts = ["placeholder"]
        
        # SBERT 시도
        if self.prefer == "sbert":
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.sbert_model_name, device=self.sbert_device)
                
                if self.sbert_max_seq_length:
                    self.model.max_seq_length = self.sbert_max_seq_length
                
                # 워밍업
                _ = self.model.encode(["warmup"], convert_to_numpy=True, show_progress_bar=False)
                
                self.kind = "sbert"
                self.meta = {
                    "backend": "sbert",
                    "model": self.sbert_model_name,
                    "device": str(self.model.device),
                    "max_seq_length": self.model.max_seq_length,
                    "batch_size": self.sbert_batch_size
                }
                print(f"[Backend] SBERT loaded: {self.sbert_model_name} (device={self.model.device})")
                return
                
            except Exception as e:
                print(f"[Backend] SBERT failed: {e}")
                print("[Backend] Falling back to TF-IDF")
        
        # TF-IDF 폴백
        self.vectorizer = TfidfVectorizer(
            ngram_range=self.tfidf_ngram,
            stop_words=self.tfidf_stopwords,
            max_features=5000,
            min_df=1  # 빈 어휘 방지
        )
        
        try:
            self.vectorizer.fit(texts)
            self.kind = "tfidf"
            self.meta = {
                "backend": "tfidf",
                "ngram_range": self.tfidf_ngram,
                "stop_words": self.tfidf_stopwords,
                "vocab_size": len(self.vectorizer.vocabulary_)
            }
            print(f"[Backend] TF-IDF initialized (vocab={len(self.vectorizer.vocabulary_)})")
        except Exception as e:
            raise RuntimeError(f"TF-IDF fit 실패: {e}")

    def transform(self, texts):
        """텍스트를 임베딩 벡터로 변환"""
        texts = [t if isinstance(t, str) and t.strip() else "placeholder" for t in texts]
        
        if self.kind == "sbert":
            emb = self.model.encode(
                texts, 
                convert_to_numpy=True, 
                normalize_embeddings=True,
                batch_size=self.sbert_batch_size, 
                show_progress_bar=False
            )
            return emb
        else:
            return self.vectorizer.transform(texts)

    def pairwise_cosine_diag(self, A, B):
        """A[i]와 B[i] 간 코사인 유사도 (대각선만)"""
        n = A.shape[0]
        sims = np.zeros(n, dtype=float)
        
        if self.kind == "sbert":
            # Dense: 정규화 완료되어 있으므로 내적
            sims = np.einsum('ij,ij->i', A, B)
        else:
            # Sparse: 행별 계산
            for i in range(n):
                if A[i].nnz > 0 and B[i].nnz > 0:
                    sims[i] = cosine_similarity(A[i], B[i])[0, 0]
        
        return np.clip(sims, -1.0, 1.0)

    def centroid(self, M):
        """임베딩 행렬의 중심 계산"""
        if M is None or M.shape[0] == 0:
            return None
            
        if self.kind == "sbert":
            c = M.mean(axis=0, keepdims=True)
            norm = np.linalg.norm(c, axis=1, keepdims=True) + 1e-12
            return c / norm
        else:
            return np.asarray(M.mean(axis=0))


# --------------------------
# PI (Participation Index)
# --------------------------
def compute_PI(
    df: pd.DataFrame,
    keywords_iterable,
    weights=[0.4, 0.3, 0.3],
    normalization: str = "minmax",
    normalization_scales: dict | None = None,
) -> pd.DataFrame:
    """
    참여 지표 계산
    
    PI = w1 × Depth + w2 × Criticality + w3 × Complexity
    (문서 기준: w1=0.4, w2=0.3, w3=0.3)
    
    구성:
    - Depth: 토큰 개수 (발화량)
    - Criticality: 비판적 키워드 비율
    - Complexity: 평균 문장 길이 + TTR (표현 복잡도)
    """
    keywords = {str(k).lower() for k in keywords_iterable}
    
    # 1) Depth: 토큰 수
    df["pi_depth_tokens"] = df["user"].apply(lambda s: len(tokenize_words(s)))
    
    # 2) Criticality: 비판적 키워드 비율
    def critical_ratio(text):
        toks = [t.lower() for t in tokenize_words(text)]
        total = len(toks)
        if total == 0:
            return 0.0
        hits = sum(1 for t in toks if t in keywords)
        return hits / total
    
    df["pi_critical_ratio"] = df["user"].apply(critical_ratio)
    
    # 3) Complexity: 평균 문장 길이 + TTR
    def avg_sent_len(text):
        tokens = tokenize_words(text)
        n_tokens = len(tokens)
        n_sents = count_sentences(text)
        return n_tokens / max(1, n_sents)
    
    def ttr(text):
        tokens = [t.lower() for t in tokenize_words(text)]
        n = len(tokens)
        return (len(set(tokens)) / n) if n > 0 else 0.0
    
    df["pi_avg_sent_len_raw"] = df["user"].apply(avg_sent_len)
    df["pi_ttr_raw"] = df["user"].apply(ttr)
    
    scales = {**DEFAULT_SINGLE_ANALYSIS_NORMALIZATION_SCALES, **(normalization_scales or {})}

    # 정규화
    df["pi_avg_sent_len"] = normalize_metric(
        df["pi_avg_sent_len_raw"],
        method=normalization,
        scale=scales["pi_avg_sent_len_raw"],
    )
    df["pi_ttr"] = normalize_metric(
        df["pi_ttr_raw"],
        method=normalization,
        scale=scales["pi_ttr_raw"],
    )
    df["pi_complexity"] = 0.5 * df["pi_avg_sent_len"] + 0.5 * df["pi_ttr"]
    
    # Depth 정규화
    df["pi_depth_norm"] = normalize_metric(
        df["pi_depth_tokens"],
        method=normalization,
        scale=scales["pi_depth_tokens"],
    )
    
    # PI 최종 계산 (가중 합)
    w1, w2, w3 = weights
    df["PI"] = (
        w1 * df["pi_depth_norm"] + 
        w2 * df["pi_critical_ratio"] + 
        w3 * df["pi_complexity"]
    )
    
    return df


# --------------------------
# UI / OI (TopicScore 포함)
# --------------------------
def compute_UI_OI(df: pd.DataFrame, backend: EmbeddingBackend, cfg) -> pd.DataFrame:
    """
    새로움(UI)과 독창성(OI) 지표 계산
    
    설계 문서 기준:
    - UI = (Distance × NewInfo) × TopicScore^α
    - OI = (1 - TopicScore) × TopicScore^β
    - TopicScore: 과제 주제 적합도 (off-topic 억제용)
    
    파라미터:
    - alpha: UI에서 TopicScore 민감도 (기본 1.0)
    - beta: OI에서 TopicScore 민감도 (기본 1.0)
    """
    alpha = cfg["ui_oi"].get("topic_score_alpha", 1.0)
    beta = cfg["ui_oi"].get("topic_score_beta", 1.0)
    min_course_samples = cfg["ui_oi"].get("min_course_samples", 3)
    normalization = cfg["ui_oi"].get("normalization", "minmax")
    scales = {
        **DEFAULT_SINGLE_ANALYSIS_NORMALIZATION_SCALES,
        **cfg["ui_oi"].get("normalization_scales", {}),
    }
    
    timings = {}

    # 데이터 준비
    before = df["chatgpt_before"].fillna("").tolist()
    essay = df["essay"].fillna("").tolist()
    
    # 백엔드 fit
    embedding_start = time.perf_counter()
    corpus = before + essay
    reuse_fitted_sbert = cfg["ui_oi"].get("reuse_fitted_sbert", False)
    should_fit_backend = not (
        reuse_fitted_sbert
        and backend.kind == "sbert"
        and backend.model is not None
    )
    if should_fit_backend:
        backend.fit(corpus)
    
    # 임베딩 변환
    E_before = backend.transform(before)
    E_essay = backend.transform(essay)
    timings["Embedding"] = time.perf_counter() - embedding_start

    ui_oi_start = time.perf_counter()
    
    # === 1) 의미 거리 (Semantic Distance) ===
    cos_diag = backend.pairwise_cosine_diag(E_before, E_essay)
    df["ui_cos_similarity"] = cos_diag
    df["ui_distance"] = np.clip(1.0 - df["ui_cos_similarity"], 0.0, 2.0)
    
    # === 2) 새정보 비율 (NewInfo Ratio) ===
    def new_info_ratio(bef, es):
        bt = set([t.lower() for t in tokenize_words(bef)])
        et = [t.lower() for t in tokenize_words(es)]
        if len(et) == 0:
            return 0.0
        new = sum(1 for t in et if t not in bt)
        return new / len(et)
    
    df["ui_newinfo_ratio"] = [
        new_info_ratio(df.loc[i, "chatgpt_before"], df.loc[i, "essay"]) 
        for i in range(len(df))
    ]
    
    # === 3) TopicScore 계산 (코스별 중심 vs essay) ===
    courses = df["course"].fillna("").astype(str).values
    
    # 코스별 인덱스 수집
    course2idx = defaultdict(list)
    for i, c in enumerate(courses):
        course2idx[c].append(i)
    
    # 코스별 중심 계산 (최소 표본 수 확인)
    course_centroid = {}
    for c, idx in course2idx.items():
        if len(idx) >= min_course_samples:
            sub = E_before[idx] if backend.kind == "sbert" else E_before[idx]
            cen = backend.centroid(sub)
            if cen is not None:
                course_centroid[c] = cen
    
    # 전역 중심 (폴백용)
    global_centroid = backend.centroid(E_before)
    
    # Essay와 코스 중심 간 유사도
    topic_scores = np.zeros(len(df), dtype=float)
    for i in range(len(df)):
        c = courses[i]
        cen = course_centroid.get(c, global_centroid)
        
        if cen is None:
            sim = 0.5  # 중립값
        else:
            if backend.kind == "sbert":
                sim = float(np.sum(E_essay[i] * cen))
            else:
                sim = cosine_similarity(E_essay[i], cen)[0, 0]
        
        topic_scores[i] = np.clip(sim, 0.0, 1.0)
    
    df["topic_score"] = topic_scores
    
    # === 4) UI 계산 (문서 기준) ===
    # UI = (Distance × NewInfo) × TopicScore^α
    df["ui_raw"] = df["ui_distance"] * df["ui_newinfo_ratio"] * (df["topic_score"] ** alpha)
    df["UI"] = normalize_metric(df["ui_raw"], method=normalization, scale=scales["ui_raw"])
    
    # === 5) OI 계산 (문서 기준) ===
    # OI = (1 - TopicScore) × TopicScore^β
    # 의미: 전형성에서 벗어났지만(1-TS), 완전히 엉뚱하지는 않음(TS^β)
    df["oi_raw"] = (1.0 - df["topic_score"]) * (df["topic_score"] ** beta)
    df["OI"] = normalize_metric(df["oi_raw"], method=normalization, scale=scales["oi_raw"])

    timings["UI/OI"] = time.perf_counter() - ui_oi_start
    df.attrs["pipeline_timings"] = {
        **df.attrs.get("pipeline_timings", {}),
        **timings,
    }
    
    return df


# --------------------------
# Weights & AIC (개선 버전)
# --------------------------
def fit_weights_and_aic(df: pd.DataFrame, cfg):
    """
    PI, UI, OI 가중치 학습 및 AIC 계산
    
    개선 사항 (문서 기준):
    1. 표준화 후 회귀 (스케일 불변)
    2. 양의 제약 회귀 (positive=True)
    3. K-fold 평균 계수 (과적합 방지)
    4. 최소 샘플 수 미만은 균등 가중치
    """
    mode = cfg["weights"]["mode"]
    clip_neg = cfg["weights"]["clip_negative"]
    min_r = int(cfg["weights"].get("min_ratings", 10))
    n_folds = int(cfg["weights"].get("n_folds", 5))
    
    if "rating_num" not in df.columns:
        df["rating_num"] = df["rating"].apply(to_num)
    
    # Equal 모드
    if mode == "equal":
        w = (1/3, 1/3, 1/3)
        df["AIC"] = (df["PI"] + df["UI"] + df["OI"]) / 3.0
        return df, w
    
    # 학습 데이터 필터링
    valid = df["rating_num"].notna() & df["PI"].notna() & df["UI"].notna() & df["OI"].notna()
    if valid.sum() < min_r:
        print(f"[Warning] 유효 샘플 부족 ({valid.sum()} < {min_r}), 균등 가중치 사용")
        w = (1/3, 1/3, 1/3)
        df["AIC"] = (df["PI"] + df["UI"] + df["OI"]) / 3.0
        return df, w
    
    X = df.loc[valid, ["PI", "UI", "OI"]].values
    y = df.loc[valid, "rating_num"].values
    
    # 표준화 (스케일 불변성)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    
    # K-fold로 계수 안정화
    n_splits = max(2, min(n_folds, valid.sum() // 2))
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    
    coefs_list = []
    for tr, _ in kf.split(Xs):
        try:
            lr = LinearRegression(positive=True)  # 양의 제약
            lr.fit(Xs[tr], y[tr])
            coefs_list.append(lr.coef_)
        except Exception as e:
            print(f"[Warning] Fold 회귀 실패: {e}")
            continue
    
    if len(coefs_list) == 0:
        print("[Warning] 모든 Fold 실패, 균등 가중치 사용")
        w = np.array([1/3, 1/3, 1/3], dtype=float)
    else:
        # 평균 계수
        betas = np.mean(coefs_list, axis=0)
        
        if clip_neg:
            betas = np.clip(betas, 0, None)
        
        # 안정성 검사
        if not np.isfinite(betas).all() or betas.sum() <= 1e-10:
            print("[Warning] 계수 불안정, 균등 가중치 사용")
            w = np.array([1/3, 1/3, 1/3], dtype=float)
        else:
            w = (betas / betas.sum()).astype(float)
    
    # AIC 계산
    df["AIC"] = df["PI"]*w[0] + df["UI"]*w[1] + df["OI"]*w[2]
    
    return df, (float(w[0]), float(w[1]), float(w[2]))


# --------------------------
# Validation (Pearson + Spearman + Bootstrap CI)
# --------------------------
def _pearson(a, b):
    """Pearson 상관계수"""
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)
    if len(a) < 3:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])

def _spearman(a, b):
    """Spearman 순위 상관계수"""
    a = pd.Series(a)
    b = pd.Series(b)
    if len(a) < 3:
        return np.nan
    ra = a.rank(method="average").values
    rb = b.rank(method="average").values
    return _pearson(ra, rb)

def _corr_ci(a, b, method="pearson", n_boot=1000, seed=42):
    """
    상관계수 + 부트스트랩 95% 신뢰구간
    
    Returns:
        (r, (ci_low, ci_high))
    """
    a = pd.Series(a)
    b = pd.Series(b)
    m = a.notna() & b.notna()
    a, b = a[m].values, b[m].values
    
    if len(a) < 3:
        return np.nan, (np.nan, np.nan)
    
    # 원본 상관
    r = _pearson(a, b) if method == "pearson" else _spearman(a, b)
    
    # 부트스트랩
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(a), len(a))
        aa, bb = a[idx], b[idx]
        rr = _pearson(aa, bb) if method == "pearson" else _spearman(aa, bb)
        if np.isfinite(rr):
            boots.append(rr)
    
    if len(boots) == 0:
        return r, (np.nan, np.nan)
    
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return r, (float(lo), float(hi))

def validate(df: pd.DataFrame) -> dict:
    """
    PI, UI, OI, AIC와 rating 간 상관 분석
    
    출력:
    - Pearson + 95% CI
    - Spearman + 95% CI
    """
    out = {}
    for col in ["PI", "UI", "OI", "AIC"]:
        p, pci = _corr_ci(df[col], df["rating_num"], method="pearson")
        s, sci = _corr_ci(df[col], df["rating_num"], method="spearman")
        out[col] = {
            "pearson": round(p, 4) if np.isfinite(p) else None,
            "pearson_ci": [round(pci[0], 4), round(pci[1], 4)] if np.isfinite(pci[0]) else [None, None],
            "spearman": round(s, 4) if np.isfinite(s) else None,
            "spearman_ci": [round(sci[0], 4), round(sci[1], 4)] if np.isfinite(sci[0]) else [None, None]
        }
    return out


# --------------------------
# Main
# --------------------------
def main(args):
    """
    메인 실행 함수
    
    개선 사항:
    1. Config 검증
    2. 단계별 타이밍 로그
    3. 메타데이터 JSON 저장
    4. 예외 처리 강화
    """
    print("=" * 70)
    print("AIC Index 계산 파이프라인 시작")
    print("=" * 70)
    
    start_time = time.time()
    timing = {}
    
    try:
        # ===== Step 1: Config 로드 및 검증 =====
        t0 = time.time()
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        
        cfg = validate_config(cfg)
        timing["config_load"] = time.time() - t0
        print(f"[Step 1] ✓ Config 로드 및 검증 완료 ({timing['config_load']:.2f}초)")
        
        # 시드 고정
        np.random.seed(int(cfg["misc"]["random_seed"]))
        
        input_csv = cfg["paths"]["input_csv"]
        out_dir = Path(cfg["paths"]["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # ===== Step 2: 데이터 로드 =====
        t0 = time.time()
        print(f"\n[Step 2] 데이터 로딩 중: {input_csv}")
        
        try:
            df = pd.read_csv(input_csv, encoding="utf-8")
        except UnicodeDecodeError:
            print("[Warning] UTF-8 실패, CP949로 재시도")
            df = pd.read_csv(input_csv, encoding="cp949")
        
        timing["data_load"] = time.time() - t0
        print(f"[Step 2] ✓ {len(df)}개 샘플 로드 ({timing['data_load']:.2f}초)")
        
        # 필수 컬럼 확인
        df = ensure_cols(df, ["chatgpt_before", "user", "essay", "rating", "course"])
        
        # 텍스트 전처리
        for c in ["chatgpt_before", "user", "essay"]:
            df[c] = df[c].fillna("").apply(safe_text)
        df["rating_num"] = df["rating"].apply(to_num)
        
        # 통계 출력
        n_total = len(df)
        n_rated = df["rating_num"].notna().sum()
        n_courses = df["course"].nunique()
        print(f"  - 총 샘플: {n_total}")
        print(f"  - 평가 있음: {n_rated} ({n_rated/n_total*100:.1f}%)")
        print(f"  - 코스 수: {n_courses}")
        
        # ===== Step 3: PI 계산 =====
        t0 = time.time()
        print(f"\n[Step 3] PI (Participation Index) 계산 중...")
        
        keywords = cfg["pi"]["critical_keywords"]
        pi_weights = cfg["pi"].get("weights", [0.4, 0.3, 0.3])
        df = compute_PI(df, keywords, weights=pi_weights)
        
        timing["pi"] = time.time() - t0
        print(f"[Step 3] ✓ PI 계산 완료 ({timing['pi']:.2f}초)")
        print(f"  - PI 평균: {df['PI'].mean():.3f}")
        print(f"  - PI 표준편차: {df['PI'].std():.3f}")
        print(f"  - 가중치(Depth:Criticality:Complexity) = {pi_weights[0]}:{pi_weights[1]}:{pi_weights[2]}")
        
        # ===== Step 4: UI/OI 계산 =====
        t0 = time.time()
        print(f"\n[Step 4] UI/OI (Uniqueness & Originality Index) 계산 중...")
        
        backend = EmbeddingBackend(
            prefer=cfg["backend"]["prefer"],
            sbert_model=cfg["backend"].get("sbert_model", "paraphrase-multilingual-mpnet-base-v2"),
            tfidf_ngram=tuple(cfg["ui_oi"].get("tfidf_ngram", [1, 2])),
            tfidf_stopwords=cfg["ui_oi"].get("tfidf_stopwords", "english"),
            sbert_batch_size=cfg["backend"].get("sbert_batch_size", 32),
            sbert_device=cfg["backend"].get("sbert_device", None),
            sbert_max_seq_length=cfg["backend"].get("sbert_max_seq_length", None)
        )
        
        df = compute_UI_OI(df, backend, cfg)
        
        timing["ui_oi"] = time.time() - t0
        print(f"[Step 4] ✓ UI/OI 계산 완료 ({timing['ui_oi']:.2f}초)")
        print(f"  - UI 평균: {df['UI'].mean():.3f}")
        print(f"  - OI 평균: {df['OI'].mean():.3f}")
        print(f"  - TopicScore 평균: {df['topic_score'].mean():.3f}")
        print(f"  - 백엔드: {backend.kind}")
        
        # ===== Step 5: 가중치 학습 & AIC 계산 =====
        t0 = time.time()
        print(f"\n[Step 5] 가중치 학습 및 AIC 계산 중...")
        
        df, weights = fit_weights_and_aic(df, cfg)
        
        timing["aic"] = time.time() - t0
        print(f"[Step 5] ✓ AIC 계산 완료 ({timing['aic']:.2f}초)")
        print(f"  - 가중치 (PI:UI:OI) = {weights[0]:.3f}:{weights[1]:.3f}:{weights[2]:.3f}")
        print(f"  - AIC 평균: {df['AIC'].mean():.3f}")
        print(f"  - AIC 표준편차: {df['AIC'].std():.3f}")
        
        # ===== Step 6: 타당성 검증 =====
        t0 = time.time()
        print(f"\n[Step 6] 타당성 검증 (상관 분석) 중...")
        
        val = validate(df)
        
        timing["validation"] = time.time() - t0
        print(f"[Step 6] ✓ 검증 완료 ({timing['validation']:.2f}초)")
        print(f"\n{'='*70}")
        print("상관 분석 결과 (rating vs 지표)")
        print(f"{'='*70}")
        for metric in ["PI", "UI", "OI", "AIC"]:
            p = val[metric]["pearson"]
            pci = val[metric]["pearson_ci"]
            s = val[metric]["spearman"]
            sci = val[metric]["spearman_ci"]
            print(f"{metric:4s} | Pearson: {p:.3f} [{pci[0]:.3f}, {pci[1]:.3f}] | Spearman: {s:.3f} [{sci[0]:.3f}, {sci[1]:.3f}]")
        print(f"{'='*70}")
        
        # ===== Step 7: 결과 저장 =====
        t0 = time.time()
        print(f"\n[Step 7] 결과 저장 중...")
        
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # CSV 저장
        cols_export = [
            "sample_id", "course", "student_id", "week", "session", "idx",
            "PI", "UI", "OI", "AIC", "rating_num",
            "pi_depth_tokens", "pi_critical_ratio", "pi_avg_sent_len", "pi_ttr", 
            "pi_complexity", "pi_depth_norm",
            "ui_cos_similarity", "ui_distance", "ui_newinfo_ratio", "topic_score"
        ]
        
        if cfg["misc"].get("export_text_columns", True):
            cols_export += ["chatgpt_before", "user", "essay"]
        
        # 컬럼 누락 방지
        for c in cols_export:
            if c not in df.columns:
                df[c] = np.nan
        
        out_csv = out_dir / f"AIC_results_{ts}.csv"
        df[cols_export].to_csv(out_csv, index=False, encoding="utf-8")
        
        # TXT 리포트 저장
        out_txt = out_dir / f"AIC_validation_{ts}.txt"
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write("AIC Index 타당성 검증 리포트\n")
            f.write("=" * 70 + "\n\n")
            
            f.write(f"생성 시각: {ts}\n")
            f.write(f"입력 파일: {input_csv}\n")
            f.write(f"총 샘플 수: {n_total}\n")
            f.write(f"평가 샘플 수: {n_rated}\n")
            f.write(f"코스 수: {n_courses}\n\n")
            
            f.write("-" * 70 + "\n")
            f.write("임베딩 백엔드 정보\n")
            f.write("-" * 70 + "\n")
            f.write(json.dumps(backend.meta, indent=2, ensure_ascii=False) + "\n\n")
            
            f.write("-" * 70 + "\n")
            f.write("PI 계산 정보\n")
            f.write("-" * 70 + "\n")
            f.write(f"가중치 (Depth:Criticality:Complexity) = {pi_weights}\n")
            f.write(f"비판적 키워드 수: {len(keywords)}\n\n")
            
            f.write("-" * 70 + "\n")
            f.write("UI/OI 계산 정보\n")
            f.write("-" * 70 + "\n")
            f.write(f"TopicScore Alpha (UI): {cfg['ui_oi']['topic_score_alpha']}\n")
            f.write(f"TopicScore Beta (OI): {cfg['ui_oi']['topic_score_beta']}\n")
            f.write(f"최소 코스 샘플 수: {cfg['ui_oi']['min_course_samples']}\n\n")
            
            f.write("-" * 70 + "\n")
            f.write("AIC 가중치\n")
            f.write("-" * 70 + "\n")
            f.write(f"모드: {cfg['weights']['mode']}\n")
            f.write(f"가중치 (PI:UI:OI) = {weights}\n\n")
            
            f.write("-" * 70 + "\n")
            f.write("지표 기술통계\n")
            f.write("-" * 70 + "\n")
            for metric in ["PI", "UI", "OI", "AIC"]:
                f.write(f"{metric}: 평균={df[metric].mean():.3f}, 표준편차={df[metric].std():.3f}, "
                       f"최소={df[metric].min():.3f}, 최대={df[metric].max():.3f}\n")
            f.write("\n")
            
            f.write("-" * 70 + "\n")
            f.write("상관 분석 결과\n")
            f.write("-" * 70 + "\n")
            f.write(json.dumps(val, indent=2, ensure_ascii=False) + "\n\n")
            
            f.write("-" * 70 + "\n")
            f.write("실행 시간 (초)\n")
            f.write("-" * 70 + "\n")
            total_time = time.time() - start_time
            timing["save"] = time.time() - t0
            timing["total"] = total_time
            f.write(json.dumps(timing, indent=2) + "\n")
        
        # JSON 메타데이터 저장
        out_json = out_dir / f"AIC_metadata_{ts}.json"
        metadata = {
            "timestamp": ts,
            "input_file": str(input_csv),
            "n_total": n_total,
            "n_rated": n_rated,
            "n_courses": n_courses,
            "backend": backend.meta,
            "pi_config": {
                "weights": pi_weights,
                "n_keywords": len(keywords)
            },
            "ui_oi_config": {
                "topic_score_alpha": cfg["ui_oi"]["topic_score_alpha"],
                "topic_score_beta": cfg["ui_oi"]["topic_score_beta"],
                "min_course_samples": cfg["ui_oi"]["min_course_samples"]
            },
            "aic_weights": {
                "mode": cfg["weights"]["mode"],
                "values": weights
            },
            "descriptive_stats": {
                metric: {
                    "mean": float(df[metric].mean()),
                    "std": float(df[metric].std()),
                    "min": float(df[metric].min()),
                    "max": float(df[metric].max())
                } for metric in ["PI", "UI", "OI", "AIC"]
            },
            "validation": val,
            "timing": timing
        }
        
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        timing["save"] = time.time() - t0
        print(f"[Step 7] ✓ 결과 저장 완료 ({timing['save']:.2f}초)")
        print(f"\n출력 파일:")
        print(f"  - CSV: {out_csv}")
        print(f"  - TXT: {out_txt}")
        print(f"  - JSON: {out_json}")
        
        # ===== 완료 =====
        total_time = time.time() - start_time
        print(f"\n{'='*70}")
        print(f"✓ 전체 파이프라인 완료 (총 {total_time:.2f}초)")
        print(f"{'='*70}\n")
        
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"✗ 오류 발생: {e}")
        print(f"{'='*70}\n")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AIC Index 계산 파이프라인 (설계 문서 완전 준수 버전)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python aic_pipeline.py --config config.yaml

Config 파일 필수 섹션:
  paths:
    input_csv: "data/input.csv"
    out_dir: "outputs/"
  
  pi:
    critical_keywords: ["however", "although", "why", "how"]
    weights: [0.4, 0.3, 0.3]  # Depth:Criticality:Complexity
  
  ui_oi:
    topic_score_alpha: 1.0
    topic_score_beta: 1.0
    min_course_samples: 3
    tfidf_ngram: [1, 2]
    tfidf_stopwords: "english"
  
  backend:
    prefer: "sbert"  # or "tfidf"
    sbert_model: "paraphrase-multilingual-mpnet-base-v2"
    sbert_batch_size: 32
  
  weights:
    mode: "auto"  # or "equal"
    min_ratings: 10
    clip_negative: true
    n_folds: 5
  
  misc:
    random_seed: 42
    export_text_columns: true
        """
    )
    parser.add_argument("--config", required=True, help="YAML 설정 파일 경로")
    args = parser.parse_args()
    
    main(args)


    
