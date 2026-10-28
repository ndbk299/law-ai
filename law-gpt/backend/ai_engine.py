"""Module AI Cốt lõi cho Law GPT (Medical AI Engine)
Bao gồm đầy đủ 4 thành phần cốt lõi:
  1. Medical Guardrails & Emergency Triggers (Bộ lọc an toàn & Phát hiện nguy cấp y tế)
  2. Medical NER (Named Entity Recognition - Nhận diện thực thể y tế tiếng Việt)
  3. RAG & Semantic Retrieval (Truy xuất tăng cường tri thức y khoa từ CSDL Dược)
  4. Generative Response Synthesis (Tổng hợp phản hồi AI - Hỗ trợ cả LLM Cloud & Local AI Engine)
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import unicodedata
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "drugs.db"
CONFIG_PATH = ROOT / "backend" / "ai_config.json"

STOP_WORDS = {
    "toi", "minh", "em", "ban", "bac", "si", "cho", "hoi", "bi", "va", "la",
    "cac", "nhung", "co", "duoc", "cua", "trong", "khi", "o", "voi", "neu",
    "mot", "nhieu", "gi", "sao", "uong", "thuoc", "can", "dung", "hay", "hoi",
    "rat", "qua", "bi", "nay", "do", "the", "nao"
}


def normalize_text(text: str) -> str:
    """Chuẩn hóa tiếng Việt: chuyển chữ thường, bỏ dấu thanh và sửa lỗi gõ phím thường gặp"""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = text.replace("đ", "d")

    # Sửa lỗi chính tả L/N hoặc gõ nhầm thường gặp
    text = re.sub(r"\bbuon\s+lon\b", "buon non", text)
    text = re.sub(r"\bmac\s+lon\b", "mac non", text)
    text = re.sub(r"\bnon\s+lon\b", "non mua", text)
    text = re.sub(r"\blon\s+mua\b", "non mua", text)
    return text.strip()


# ==============================================================================
# PHẦN 1: MEDICAL GUARDRAILS & EMERGENCY TRIGGERS (BỘ LỌC AN TOÀN & NGUY CẤP)
# ==============================================================================

EMERGENCY_PATTERNS = [
    # Dấu hiệu nhồi máu cơ tim / mạch vành cấp
    (r"\b(dau that nguc|dau nguc du doi|nguc bi de nang|dau lan ra tay|dau tim cap)\b",
     "Đau thắt ngực dữ dội nghi ngờ hội chứng mạch vành cấp hoặc nhồi máu cơ tim."),
    # Dấu hiệu suy hô hấp nặng
    (r"\b(khong tho duoc|kho tho du doi|tim tai|ngat tho|tho rit thanh quan)\b",
     "Suy hô hấp cấp tính, khó thở nghiêm trọng đe dọa tính mạng."),
    # Dấu hiệu đột quỵ não (FAST)
    (r"\b(liet nua nguoi|meo mieng|noi ngong dot ngot|mat thi luc dot ngot|yeu tay chan dot ngot)\b",
     "Các dấu hiệu cảnh báo đột quỵ não cấp tính (FAST)."),
    # Dấu hiệu bụng ngoại khoa cấp cứu (viêm ruột thừa cấp, thủng tạng rỗng)
    (r"\b(bung go cung|bung cung nhu go|dau ruot thua|dau bung du doi quan that)\b",
     "Đau bụng dữ dội kèm co cứng thành bụng như gỗ nghi ngờ viêm ruột thừa cấp hoặc bụng ngoại khoa."),
    # Sốc phản vệ / Ngộ độc
    (r"\b(soc phan ve|uong qua lieu|ngo doc thuoc|uong nham thuoc|non ra mau|di ngoai ra mau)\b",
     "Dấu hiệu sốc phản vệ, ngộ độc thuốc cấp hoặc xuất huyết nội tạng nặng."),
    # Co giật, mất ý thức
    (r"\b(co giat|ngat xiu|hon me|bat tinh|mat y thuc)\b",
     "Trạng thái co giật, hôn mê hoặc mất tri giác cấp tính."),
]


class MedicalGuardrails:
    """Bộ lọc an toàn y tế và nhận diện tình trạng cấp cứu"""

    @staticmethod
    def check_emergency(query: str) -> tuple[bool, str]:
        norm = normalize_text(query)
        for pattern, reason in EMERGENCY_PATTERNS:
            if re.search(pattern, norm):
                return True, reason
        return False, ""

    @staticmethod
    def build_emergency_response(reason: str) -> dict:
        return {
            "reply": (
                "🚨 **CẢNH BÁO NGUY CẤP Y TẾ!**\n\n"
                f"Hệ thống phát hiện dấu hiệu nguy hiểm tính mạng: **{reason}**\n\n"
                "⚠️ **HÀNH ĐỘNG KHẨN CẤP:**\n"
                "1. Hãy gọi ngay cấp cứu **115** hoặc di chuyển khẩn trương đến khoa Cấp cứu của bệnh viện gần nhất!\n"
                "2. **TUYỆT ĐỐI KHÔNG** tự ý mua hoặc uống thuốc qua mạng trong tình huống này.\n"
                "3. Giữ bệnh nhân ở tư thế thoải mái, thoáng khí và luôn có người theo dõi liên tục."
            ),
            "choices": [
                {"label": "📞 Gọi cấp cứu 115", "query": "cấp cứu"},
                {"label": "Bệnh viện gần nhất", "query": "bệnh viện"},
                {"label": "Chọn nhóm thuốc khác", "query": "nhóm thuốc"},
            ],
            "ai_metadata": {
                "is_emergency": True,
                "reason": reason,
                "provider": "guardrails",
            }
        }


# ==============================================================================
# PHẦN 2: MEDICAL NER (NAMED ENTITY RECOGNITION - NHẬN DIỆN THỰC THỂ Y TẾ)
# ==============================================================================

SYMPTOM_DICTIONARY = {
    # 1. Giảm đau - Hạ sốt
    "sot cao": ("Sốt cao", "giam-dau"),
    "sot": ("Sốt, tăng thân nhiệt", "giam-dau"),
    "nong sot": ("Sốt, nóng sốt", "giam-dau"),
    "dau dau": ("Đau đầu, nhức đầu", "giam-dau"),
    "nhuc dau": ("Đau đầu, nhức đầu", "giam-dau"),
    "dau nua dau": ("Đau nửa đầu", "giam-dau"),
    "dau rang": ("Đau răng", "giam-dau"),
    "dau co": ("Đau nhức cơ xương khớp", "giam-dau"),
    "nhuc moi": ("Đau nhức mỏi cơ thể", "giam-dau"),
    "dau nhuc": ("Đau nhức cơ thể", "giam-dau"),
    "dau bung kinh": ("Đau bụng kinh", "giam-dau"),
    "viem khop": ("Viêm khớp, thoái hóa khớp", "giam-dau"),

    # 2. Hô hấp
    "ho co dom": ("Ho có đờm đặc", "ho-hap"),
    "ho": ("Ho, ngứa họng", "ho-hap"),
    "dom": ("Tăng tiết đờm nhầy", "ho-hap"),
    "viem hong": ("Viêm họng, đau rát họng", "ho-hap"),
    "dau hong": ("Đau rát họng", "ho-hap"),
    "nghet mui": ("Nghẹt mũi, ngạt mũi", "ho-hap"),
    "so mui": ("Sổ mũi, chảy nước mũi", "ho-hap"),
    "chay nuoc mui": ("Sổ mũi, chảy nước mũi", "ho-hap"),
    "hat hoi": ("Hắt hơi", "di-ung"),
    "cam cum": ("Cảm cúm, cảm lạnh", "ho-hap"),
    "kho tho": ("Khó thở nhẹ, co thắt phế quản", "ho-hap"),
    "hen suyen": ("Hen suyễn, co thắt phế quản", "ho-hap"),

    # 3. Dị ứng
    "di ung": ("Dị ứng, phản ứng quá mẫn", "di-ung"),
    "ngua": ("Mẩn ngứa da", "di-ung"),
    "me day": ("Mề đay, phát ban", "di-ung"),
    "man ngua": ("Mẩn ngứa", "di-ung"),
    "viem mui di ung": ("Viêm mũi dị ứng", "di-ung"),

    # 4. Tiêu hóa - Dạ dày - Ruột
    "dau bung": ("Đau bụng, co thắt tiêu hóa", "tieu-hoa"),
    "dau bung duoi": ("Đau bụng dưới", "tieu-hoa"),
    "bung cung": ("Bụng căng chướng khó tiêu", "tieu-hoa"),
    "cang bung": ("Bụng căng chướng", "tieu-hoa"),
    "dau da day": ("Đau dạ dày, viêm dạ dày", "tieu-hoa"),
    "dau bao tu": ("Đau dạ dày, viêm dạ dày", "tieu-hoa"),
    "dau thuong vi": ("Đau vùng thượng vị dạ dày", "tieu-hoa"),
    "trao nguoc": ("Trào ngược dạ dày thực quản (GERD)", "tieu-hoa"),
    "o nong": ("Ợ nóng, nóng rát thực quản", "tieu-hoa"),
    "o chua": ("Ợ chua", "tieu-hoa"),
    "loet da day": ("Loét dạ dày tá tràng", "tieu-hoa"),
    "buon non": ("Buồn nôn, nôn nao", "tieu-hoa"),
    "non mua": ("Nôn mửa", "tieu-hoa"),
    "mac non": ("Buồn nôn", "tieu-hoa"),
    "non": ("Nôn ói", "tieu-hoa"),
    "tieu chay": ("Tiêu chảy, đi ngoài phân lỏng", "tieu-hoa"),
    "di ngoai": ("Tiêu chảy, đi ngoài lỏng", "tieu-hoa"),
    "day bung": ("Đầy bụng, khó tiêu", "tieu-hoa"),
    "chuong bung": ("Chướng bụng, đầy hơi", "tieu-hoa"),
    "kho tieu": ("Khó tiêu, đầy hơi", "tieu-hoa"),
    "roi loan tieu hoa": ("Rối loạn tiêu hóa", "tieu-hoa"),

    # 5. Kháng sinh / Nhiễm trùng
    "nhiem khuan": ("Nhiễm khuẩn đường hô hấp / tiết niệu", "khang-sinh"),
    "viem xoang": ("Viêm xoang nhiễm khuẩn", "khang-sinh"),
    "viem tai": ("Viêm tai giữa", "khang-sinh"),

    # 6. Tim mạch / Nội tiết
    "cao huyet ap": ("Tăng huyết áp", "tim-mach"),
    "huyet ap cao": ("Tăng huyết áp", "tim-mach"),
    "mo mau": ("Rối loạn mỡ máu, tăng cholesterol", "tim-mach"),
    "tieu duong": ("Đái tháo đường týp 2", "noi-tiet"),
    "duong huyet": ("Đường huyết cao", "noi-tiet"),
    "suy giap": ("Suy giáp, bệnh tuyến giáp", "noi-tiet"),

    # 7. Vitamin
    "met moi": ("Mệt mỏi, suy nhược thể chất", "vitamin"),
    "suy nhuoc": ("Suy nhược cơ thể", "vitamin"),
    "thieu mau": ("Thiếu máu do thiếu sắt", "vitamin"),
    "loang xuong": ("Phòng ngừa loãng xương, thiếu canxi", "vitamin"),
}

DEMOGRAPHIC_DICTIONARY = {
    "tre em": "Trẻ em",
    "em be": "Trẻ nhỏ",
    "so sinh": "Trẻ sơ sinh",
    "ba bau": "Phụ nữ mang thai",
    "mang thai": "Phụ nữ mang thai",
    "co thai": "Phụ nữ mang thai",
    "cho con bu": "Phụ nữ đang cho con bú",
    "nguoi gia": "Người cao tuổi",
    "nguoi lon tuoi": "Người cao tuổi",
}

CONDITION_DICTIONARY = {
    "loet da day": "Tiền sử viêm loét dạ dày",
    "suy gan": "Bệnh lý suy gan",
    "men gan": "Tăng men gan",
    "suy than": "Bệnh lý suy thận",
    "hen": "Tiền sử hen phế quản",
    "tim mach": "Bệnh tim mạch",
    "tieu duong": "Bệnh đái tháo đường",
}


class MedicalNER:
    """Bộ bóc tách thực thể y tế tiếng Việt (Symptoms, Demographics, Conditions, Intent)"""

    @classmethod
    def extract_entities(cls, text: str) -> dict:
        norm = normalize_text(text)
        symptoms = []
        target_groups = []

        # Sắp xếp các cụm từ triệu chứng dài trước để ưu tiên (VD: 'dau bung duoi' trước 'dau bung')
        sorted_symptom_terms = sorted(SYMPTOM_DICTIONARY.keys(), key=lambda x: len(x), reverse=True)

        for term in sorted_symptom_terms:
            if re.search(r"\b" + re.escape(term) + r"\b", norm):
                std_name, grp = SYMPTOM_DICTIONARY[term]
                if std_name not in symptoms:
                    symptoms.append(std_name)
                if grp not in target_groups:
                    target_groups.append(grp)

        # 2. Bóc tách đối tượng người bệnh
        demographics = []
        for term, std_demo in DEMOGRAPHIC_DICTIONARY.items():
            if re.search(r"\b" + re.escape(term) + r"\b", norm):
                if std_demo not in demographics:
                    demographics.append(std_demo)

        # 3. Bóc tách bệnh nền / tiền sử
        conditions = []
        for term, std_cond in CONDITION_DICTIONARY.items():
            if re.search(r"\b" + re.escape(term) + r"\b", norm):
                if std_cond not in conditions:
                    conditions.append(std_cond)

        # 4. Xác định ý định người dùng (Intent)
        intent = "GENERAL_SEARCH"
        if re.search(r"\b(chao|xin chao|hello|hi)\b", norm):
            intent = "GREETING"
        elif "tac dung phu" in norm or "uong vao bi" in norm:
            intent = "SIDE_EFFECTS"
        elif "chong chi dinh" in norm or "ai khong duoc uong" in norm:
            intent = "CONTRAINDICATION"
        elif "lieu dung" in norm or "uong the nao" in norm or "ngay may vien" in norm:
            intent = "DOSAGE"
        elif symptoms:
            intent = "SYMPTOM_CONSULTATION"

        return {
            "symptoms": symptoms,
            "target_groups": target_groups,
            "demographics": demographics,
            "conditions": conditions,
            "intent": intent,
        }


# ==============================================================================
# PHẦN 3: RAG (RETRIEVAL-AUGMENTED GENERATION) & SEMANTIC RETRIEVAL
# ==============================================================================

class MedicalRAG:
    """Hệ thống tìm kiếm ngữ nghĩa và truy xuất tri thức Dược lâm sàng"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._corpus: list[dict] = []
        self._tfidf_docs: list[dict[str, float]] = []
        self._idf: dict[str, float] = {}
        self._load_and_index()

    def _load_and_index(self):
        if not self.db_path.exists():
            return
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT d.*, g.name AS group_name
            FROM drugs d
            JOIN drug_groups g ON d.group_id = g.id
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        self._corpus = rows
        total_docs = len(rows)
        doc_freq: dict[str, int] = {}

        for doc in rows:
            text = " ".join([
                doc["name"],
                doc["active_ingredient"],
                doc["group_name"],
                doc.get("indications", ""),
                doc.get("form", ""),
                doc.get("dosage", ""),
            ])
            raw_tokens = normalize_text(text).split()
            tokens = {t for t in raw_tokens if t not in STOP_WORDS and len(t) > 1}
            for t in tokens:
                doc_freq[t] = doc_freq.get(t, 0) + 1

        self._idf = {
            t: math.log((total_docs + 1) / (df + 1)) + 1.0
            for t, df in doc_freq.items()
        }

        for doc in rows:
            text = " ".join([
                doc["name"],
                doc["active_ingredient"],
                doc["group_name"],
                doc.get("indications", ""),
                doc.get("form", ""),
            ])
            raw_tokens = normalize_text(text).split()
            tokens = [t for t in raw_tokens if t not in STOP_WORDS and len(t) > 1]
            tf: dict[str, float] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0.0) + 1.0
            doc_vec = {t: (count / (len(tokens) or 1)) * self._idf.get(t, 1.0) for t, count in tf.items()}
            self._tfidf_docs.append(doc_vec)

    def retrieve(self, query: str, target_groups: list[str] | None = None, demographic_filter: list[str] | None = None, top_k: int = 4) -> list[dict]:
        """Truy xuất các thuốc phù hợp nhất theo Vector Cosine Similarity & Nhóm bệnh lý"""
        if not self._corpus:
            return []

        raw_q_tokens = normalize_text(query).split()
        q_tokens = [t for t in raw_q_tokens if t not in STOP_WORDS and len(t) > 1]
        if not q_tokens:
            q_tokens = raw_q_tokens

        q_tf: dict[str, float] = {}
        for t in q_tokens:
            q_tf[t] = q_tf.get(t, 0.0) + 1.0
        q_vec = {t: (count / len(q_tokens)) * self._idf.get(t, 1.0) for t, count in q_tf.items()}

        scores = []
        for idx, doc_vec in enumerate(self._tfidf_docs):
            dot_product = sum(q_vec[t] * doc_vec.get(t, 0.0) for t in q_vec)
            q_norm = math.sqrt(sum(v ** 2 for v in q_vec.values())) or 1.0
            doc_norm = math.sqrt(sum(v ** 2 for v in doc_vec.values())) or 1.0
            score = dot_product / (q_norm * doc_norm)

            doc = self._corpus[idx]

            # 1. Trọng số nhóm: nếu thuốc thuộc nhóm đích của triệu chứng vừa bóc tách, boost điểm mạnh mẽ
            if target_groups and doc["group_id"] in target_groups:
                score += 0.55

            # 2. Khớp trực tiếp tên biệt dược hoặc hoạt chất
            norm_name = normalize_text(doc["name"])
            norm_active = normalize_text(doc["active_ingredient"])
            if any(t in norm_name for t in q_tokens if len(t) > 2):
                score += 0.5
            if any(t in norm_active for t in q_tokens if len(t) > 2):
                score += 0.4

            # 3. Kiểm tra An toàn & Chống chỉ định theo nhóm đối tượng
            contra = normalize_text(doc.get("contraindications", ""))
            warning = None
            if demographic_filter:
                if "Phụ nữ mang thai" in demographic_filter and ("phu nu co thai" in contra or "mang thai" in contra or "say thai" in contra):
                    warning = "⚠️ CẢNH BÁO AN TOÀN: Thuốc chống chỉ định hoặc cần thận trọng cao ở phụ nữ mang thai!"
                    score -= 0.6
                if "Trẻ sơ sinh" in demographic_filter and ("tre em duoi" in contra or "tre so sinh" in contra):
                    warning = "⚠️ CẢNH BÁO AN TOÀN: Chống chỉ định cho trẻ nhỏ/trẻ sơ sinh!"
                    score -= 0.6

            scores.append((score, doc, warning))

        scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for s, doc, warn in scores[:top_k]:
            if s > 0.02 or len(results) == 0:
                item = dict(doc)
                item["_relevance_score"] = round(s, 3)
                item["_safety_warning"] = warn
                results.append(item)
        return results


# ==============================================================================
# PHẦN 4: GENERATIVE LLM RESPONSE SYNTHESIS (TỔNG HỢP PHẢN HỒI AI)
# ==============================================================================

class LLMProviderError(RuntimeError):
    """Lỗi cấu hình hoặc kết nối tới nhà cung cấp mô hình ngôn ngữ."""


class MedicalLLMGenerator:
    """Sinh phản hồi bằng Gemini, OpenAI, Ollama hoặc bộ xử lý nội bộ."""

    def __init__(self):
        cfg = {}
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LLMProviderError(f"Không đọc được cấu hình LLM tại {CONFIG_PATH}: {exc}") from exc
            if not isinstance(cfg, dict):
                raise LLMProviderError(f"Cấu hình LLM tại {CONFIG_PATH} phải là một JSON object.")

        self.api_keys = {
            "gemini": os.environ.get("GEMINI_API_KEY") or cfg.get("gemini_api_key", ""),
            "openai": os.environ.get("OPENAI_API_KEY") or cfg.get("openai_api_key", ""),
        }
        selected_provider = os.environ.get("AI_PROVIDER") or cfg.get("provider")
        if selected_provider:
            self.provider = str(selected_provider).strip().lower()
        elif self.api_keys["gemini"]:
            self.provider = "gemini"
        elif self.api_keys["openai"]:
            self.provider = "openai"
        elif os.environ.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_BASE_URL"):
            self.provider = "ollama"
        else:
            self.provider = "local"

        if self.provider not in {"gemini", "openai", "ollama", "local"}:
            raise LLMProviderError(
                "AI_PROVIDER không hợp lệ. Chọn gemini, openai, ollama hoặc local."
            )
        if self.provider in self.api_keys and not self.api_keys[self.provider]:
            raise LLMProviderError(f"Thiếu API key cho AI_PROVIDER={self.provider}.")

        self.models = {
            "gemini": os.environ.get("GEMINI_MODEL") or cfg.get("gemini_model") or "gemini-2.5-flash",
            "openai": os.environ.get("OPENAI_MODEL") or cfg.get("openai_model") or "gpt-4o-mini",
            "ollama": os.environ.get("OLLAMA_MODEL") or cfg.get("ollama_model") or "llama3.2",
        }
        self.openai_base_url = (
            os.environ.get("OPENAI_BASE_URL")
            or cfg.get("openai_base_url")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.ollama_base_url = (
            os.environ.get("OLLAMA_BASE_URL")
            or cfg.get("ollama_base_url")
            or "http://localhost:11434"
        ).rstrip("/")
        try:
            self.timeout = float(os.environ.get("AI_TIMEOUT_SECONDS", "30"))
        except ValueError as exc:
            raise LLMProviderError("AI_TIMEOUT_SECONDS phải là số dương.") from exc
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise LLMProviderError("AI_TIMEOUT_SECONDS phải là số dương.")

    def _post_json(self, url: str, payload: dict, headers: dict, provider: str) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMProviderError(f"{provider} API trả về HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMProviderError(f"Không thể kết nối tới {provider} API: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"{provider} API trả về dữ liệu JSON không hợp lệ.") from exc
        if not isinstance(data, dict):
            raise LLMProviderError(f"{provider} API trả về dữ liệu không đúng định dạng.")
        return data

    @staticmethod
    def _response_text(data: dict, provider: str) -> str:
        try:
            if provider == "gemini":
                parts = data["candidates"][0]["content"]["parts"]
                text = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str))
            elif provider == "openai":
                text = data["choices"][0]["message"]["content"]
            else:
                text = data["message"]["content"]
        except (AttributeError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(f"{provider} API không trả về nội dung câu trả lời hợp lệ.") from exc
        if not isinstance(text, str) or not text.strip():
            raise LLMProviderError(f"{provider} API trả về câu trả lời rỗng.")
        return text.strip()

    def _call_provider(self, messages: list[dict]) -> str:
        headers = {"Content-Type": "application/json"}
        if self.provider == "gemini":
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.models['gemini']}:generateContent"
            )
            headers["x-goog-api-key"] = self.api_keys["gemini"]
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": messages[0]["content"] + "\n\n" + messages[1]["content"]}],
                    }
                ],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800},
            }
        elif self.provider == "openai":
            url = f"{self.openai_base_url}/chat/completions"
            headers["Authorization"] = f"Bearer {self.api_keys['openai']}"
            payload = {
                "model": self.models["openai"],
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 800,
            }
        else:
            url = f"{self.ollama_base_url}/api/chat"
            payload = {
                "model": self.models["ollama"],
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 800},
            }

        response = self._post_json(url, payload, headers, self.provider)
        return self._response_text(response, self.provider)

    def generate(self, user_query: str, entities: dict, retrieved_drugs: list[dict]) -> tuple[str, list[dict]]:
        if self.provider != "local":
            context_text = "\n\n".join([
                f"- Tên thuốc: {d['name']} ({d['active_ingredient']})\n"
                f"  Dạng bào chế: {d['form']} | Nhóm: {d['group_name']}\n"
                f"  Số ĐK: {d['registration_no']} | Hãng: {d['manufacturer']}\n"
                f"  Chỉ định: {d.get('indications', '')}\n"
                f"  Liều dùng: {d.get('dosage', '')}\n"
                f"  Chống chỉ định: {d.get('contraindications', '')}\n"
                f"  Tác dụng phụ: {d.get('side_effects', '')}"
                for d in retrieved_drugs
            ]) or "(Không tìm thấy tài liệu thuốc phù hợp trong cơ sở dữ liệu.)"
            system_prompt = (
                "Bạn là Trợ lý AI Dược phẩm Law GPT. Trả lời bằng tiếng Việt tự nhiên, rõ ràng và ân cần. "
                "Chỉ dùng tài liệu thuốc được cung cấp; không tự bịa thuốc, chỉ định hoặc liều dùng. "
                "Nếu tài liệu không có thông tin để trả lời, hãy nói rõ điều đó và khuyến nghị hỏi bác sĩ/dược sĩ. "
                "Không chẩn đoán bệnh và luôn nhắc thông tin chỉ mang tính tham khảo."
            )
            user_prompt = (
                f"Tài liệu thuốc:\n{context_text}\n\n"
                f"Câu hỏi: {user_query}\n"
                f"Thông tin nhận diện: triệu chứng={entities.get('symptoms', [])}, "
                f"đối tượng={entities.get('demographics', [])}, "
                f"tiền sử={entities.get('conditions', [])}.\n"
                "Trả lời ngắn gọn, nêu cảnh báo chống chỉ định nếu có và kết thúc bằng khuyến cáo "
                "tham khảo ý kiến bác sĩ/dược sĩ."
            )
            cloud_reply = self._call_provider([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            choices = [{"label": d["name"], "query": d["name"]} for d in retrieved_drugs[:4]]
            choices.append({"label": "Chọn nhóm khác", "query": "nhóm thuốc"})
            return cloud_reply, choices

        # Bộ xử lý nội bộ giữ vai trò dự phòng khi không cấu hình dịch vụ LLM.
        intent = entities["intent"]
        symptoms = entities["symptoms"]
        demos = entities["demographics"]
        conditions = entities["conditions"]
        q_norm = normalize_text(user_query)

        # Kiểm tra xem người dùng có đang hỏi trực tiếp tên thuốc cụ thể hay không
        is_direct_drug_search = False
        if retrieved_drugs:
            top_d = retrieved_drugs[0]
            name_norm = normalize_text(top_d["name"])
            active_norm = normalize_text(top_d["active_ingredient"])
            # Tên thuốc xuất hiện trong câu hỏi
            if name_norm in q_norm or any(part in q_norm for part in name_norm.split() if len(part) >= 4):
                is_direct_drug_search = True
            elif active_norm in q_norm:
                is_direct_drug_search = True

        reply_lines = []

        if intent == "GREETING":
            reply_lines.append(
                "👋 **Xin chào! Mình là Trợ lý AI Dược phẩm Law GPT (Infranixx).**\n"
                "Hệ thống vận hành với kiến trúc AI Y tế 4 lớp: *Medical Guardrails*, *Medical NER*, *RAG Semantic Retrieval* và *Generative Synthesis*.\n\n"
                "Bạn có thể nhắn triệu chứng (ví dụ: *'đau đầu sốt cao'*, *'đau bụng buồn nôn'*, *'viêm họng có đờm'*), hỏi tên biệt dược, hoặc bấm chọn các nhóm thuốc bên dưới nhé!"
            )
            choices = [{"label": d["name"], "query": d["name"]} for d in retrieved_drugs[:4]]
            choices.append({"label": "Chọn nhóm khác", "query": "nhóm thuốc"})
            return "\n\n".join(reply_lines), choices

        if intent == "SIDE_EFFECTS" and retrieved_drugs:
            d = retrieved_drugs[0]
            reply_lines.append(f"⚠️ **Thông tin an toàn & Tác dụng phụ của {d['name']} ({d['active_ingredient']}):**\n")
            reply_lines.append(f"• **Tác dụng phụ thường gặp:** {d.get('side_effects', 'Chưa ghi nhận phản ứng bất lợi ở liều thông thường.')}")
            reply_lines.append(f"• **Chống chỉ định quan trọng:** {d.get('contraindications', 'Theo hướng dẫn sử dụng.')}")
            reply_lines.append("\n*Nếu gặp phản ứng bất thường hoặc khó thở, hãy ngừng dùng thuốc ngay và tham khảo ý kiến chuyên gia y tế.*")
            choices = [
                {"label": f"Xem {d['name']}", "query": d["name"]},
                {"label": "Thuốc cùng nhóm", "query": d["group_name"]},
                {"label": "Chọn nhóm khác", "query": "nhóm thuốc"},
            ]
            return "\n".join(reply_lines), choices

        # Nhánh 1: Người dùng mô tả triệu chứng bệnh
        if symptoms:
            sym_str = ", ".join(symptoms)
            demo_str = f" ở đối tượng **{', '.join(demos)}**" if demos else ""
            cond_str = f" (Tiền sử: *{', '.join(conditions)}*)" if conditions else ""
            reply_lines.append(f"🩺 **Phân tích lâm sàng:** Tiếp nhận triệu chứng **{sym_str}**{demo_str}{cond_str}.")
            reply_lines.append("Dựa trên dữ liệu Dược thư Quốc gia (Cục Quản lý Dược – Bộ Y tế), các thuốc phù hợp gồm:")

            for d in retrieved_drugs[:3]:
                warn_prefix = f"\n  {d['_safety_warning']}" if d.get("_safety_warning") else ""
                reply_lines.append(
                    f"\n💊 **{d['name']}** ({d['active_ingredient']} - {d['strength']})\n"
                    f"  • *Dạng bào chế:* {d['form']}\n"
                    f"  • *Số đăng ký:* `{d['registration_no']}` ({d['manufacturer']})\n"
                    f"  • *Chỉ định:* {d.get('indications', '')}\n"
                    f"  • *Liều dùng tham khảo:* {d.get('dosage', 'Theo chỉ định của bác sĩ')}{warn_prefix}"
                )

            reply_lines.append("\n💡 *Lưu ý: Thông tin trên mang tính chất tham khảo. Hãy tham khảo ý kiến dược sĩ/bác sĩ trước khi dùng, đặc biệt với phụ nữ mang thai hoặc trẻ nhỏ.*")
            choices = [{"label": d["name"], "query": d["name"]} for d in retrieved_drugs[:4]]
            choices.append({"label": "Chọn nhóm khác", "query": "nhóm thuốc"})
            return "\n".join(reply_lines), choices

        # Nhánh 2: Người dùng đích danh tra cứu 1 loại thuốc cụ thể
        elif is_direct_drug_search and retrieved_drugs:
            d = retrieved_drugs[0]
            reply_lines.append(f"📋 **Hồ sơ thuốc trích xuất từ CSDL Dược: {d['name']}**\n")
            reply_lines.append(f"• **Hoạt chất:** {d['active_ingredient']} ({d['strength']})")
            reply_lines.append(f"• **Dạng bào chế:** {d['form']} – Hãng: {d['manufacturer']} ({d.get('country', 'Việt Nam')})")
            reply_lines.append(f"• **Số đăng ký Bộ Y tế:** `{d['registration_no']}`")
            reply_lines.append(f"• **Chỉ định:** {d.get('indications', '')}")
            reply_lines.append(f"• **Liều lượng tham khảo:** {d.get('dosage', '')}")
            if d.get("contraindications"):
                reply_lines.append(f"• **Chống chỉ định:** {d['contraindications']}")
            reply_lines.append("\n👉 *Bấm vào nút bên dưới để xem chi tiết tờ thông tin thuốc.*")
            choices = [{"label": f"Xem {d['name']}", "query": d["name"]}, {"label": "Thuốc cùng nhóm", "query": d["group_name"]}, {"label": "Chọn nhóm khác", "query": "nhóm thuốc"}]
            return "\n".join(reply_lines), choices

        # Nhánh 3: Không rõ triệu chứng và không phải tên thuốc cụ thể
        else:
            reply_lines.append(
                f"🤔 **Ghi nhận yêu cầu:** “*{user_query}*”.\n"
                "Hệ thống chưa nhận diện rõ triệu chứng hoặc tên thuốc từ câu hỏi của bạn.\n\n"
                "💡 **Để được hỗ trợ tốt nhất, bạn có thể:**\n"
                "• Miêu tả cụ thể triệu chứng (ví dụ: *'đau đầu sốt cao'*, *'đau bụng buồn nôn'*, *'viêm họng có đờm'*).\n"
                "• Hoặc bấm chọn nhanh các nhóm thuốc bên dưới để xem danh mục chi tiết:"
            )
            choices = [{"label": d["name"], "query": d["name"]} for d in retrieved_drugs[:4]]
            choices.append({"label": "Chọn nhóm khác", "query": "nhóm thuốc"})
            return "\n".join(reply_lines), choices


# ==============================================================================
# BỘ ĐIỀU PHỐI AI TỔNG THỂ (MAIN AI PIPELINE)
# ==============================================================================

class MedicalAIEngine:
    """Đầu mối tích hợp quy trình AI 4 lớp của Law GPT"""

    def __init__(self):
        self.guardrails = MedicalGuardrails()
        self.ner = MedicalNER()
        self.rag = MedicalRAG()
        self.llm = MedicalLLMGenerator()

    def process(self, query: str, current_group: str | None = None) -> dict:
        # 1. Kiểm tra An toàn & Nguy cấp (Guardrails)
        is_emergency, reason = self.guardrails.check_emergency(query)
        if is_emergency:
            return self.guardrails.build_emergency_response(reason)

        # 2. Nhận diện Thực thể Y tế (Medical NER)
        entities = self.ner.extract_entities(query)

        # 3. Truy xuất ngữ nghĩa từ CSDL Dược (RAG Retrieval)
        retrieved_drugs = self.rag.retrieve(
            query=query,
            target_groups=entities["target_groups"],
            demographic_filter=entities["demographics"],
            top_k=4
        )

        # 4. Sinh phản hồi có căn cứ tri thức (LLM Generation)
        reply_text, choices = self.llm.generate(query, entities, retrieved_drugs)

        return {
            "reply": reply_text,
            "choices": choices,
            "ai_metadata": {
                "is_emergency": False,
                "provider": self.llm.provider,
                "entities": entities,
                "retrieved_count": len(retrieved_drugs),
                "top_drug": retrieved_drugs[0]["name"] if retrieved_drugs else None
            }
        }


# Singleton instance
ai_engine = MedicalAIEngine()
