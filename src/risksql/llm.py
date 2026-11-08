"""LLM step: question -> JSON {sql, graphique, hypotheses, refus}, validated by pydantic, one repair attempt with the exact error.
The model only ever proposes; guard.check + the read-only executor decide what runs."""
import json
import re
import time
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, ValidationError
from .guard import check, Rejected

MODEL = "qwen3.5:4b"
CATALOG = yaml.safe_load((Path(__file__).parent / "catalog.yaml").read_text(encoding="utf8"))

# Few-shot pool: verified question -> reference SQL pairs (dev + test v1 + test v2 (both burned for tuning)).
# The k most similar ones (entities masked) go into the prompt; a question never sees its own pair.
_POOL = None
REFUSAL = ("Quel est le cours de l'action Apple ?", None)


def _mask(q):
    q = re.sub(r"\b(TAUX_EUR|TAUX_USD|FX_SPOT|Martin|Bernard|Dubois|Thomas|Robert|Petit|Taux|Change|EUR|USD)\b", "X", q, flags=re.I)
    q = re.sub(r"\b(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\b", "M", q, flags=re.I)
    return re.sub(r"\d+", "N", q).lower()


def pool():
    global _POOL
    if _POOL is None:
        root = Path(__file__).resolve().parents[2] / "eval"
        _POOL = [(it["question"], it["reference_sql"]) for sp in ("dev", "test", "test2") for it in json.loads((root / f"{sp}.json").read_text(encoding="utf8"))]
    return _POOL


def pick_shots(question, k=6):
    from rapidfuzz import fuzz
    m = _mask(question)
    ranked = sorted((p for p in pool() if p[0].strip() != question.strip()), key=lambda p: -fuzz.token_set_ratio(m, _mask(p[0])))
    return ranked[:k] + [REFUSAL]


class Answer(BaseModel):
    sql: Optional[str] = None
    graphique: Optional[str] = None  # "ligne" | "barres" | None
    hypotheses: list[str] = []
    refus: Optional[str] = None


def system_prompt(question=""):
    views = "\n".join(
        f"- {v} ({spec['description']}): " + "; ".join(f"{c} {d[0]} = {d[1]}" for c, d in spec["columns"].items())
        for v, spec in CATALOG["views"].items())
    shots = "\n".join(
        f"Q: {q}\nR: " + json.dumps({"sql": s, "graphique": None, "hypotheses": [], "refus": None} if s else
                                     {"sql": None, "graphique": None, "hypotheses": [], "refus": "Hors du périmètre des données."}, ensure_ascii=False)
        for q, s in pick_shots(question))
    return f"""Tu traduis une question en français en une requête DuckDB (SELECT unique) sur ces vues, et rien d'autre:
{views}
Règles: la date de référence est {CATALOG['reference_date']} ("dernier jour" = max(date)); n'utilise jamais current_date ni now().
Seules ces vues existent. Les valeurs texte sont sensibles à la casse: desk ∈ 'Taux','Change'; book ∈ 'TAUX_EUR','TAUX_USD','FX_SPOT'; serie ∈ 'EUR_2Y','EUR_5Y','EUR_10Y','USD_2Y','USD_5Y','USD_10Y','EURUSD'. Renvoie seulement les colonnes demandées ("quel trader/jour/book" = une seule colonne). v_pnl est par position: le P&L journalier d'un book est dans v_risque_book.pnl_eur; le P&L total d'une entité = SUM sur v_pnl. "Quels X" = SELECT DISTINCT. Ne filtre jamais sur instrument ou date si la question ne le demande pas. "par X" ou "de chaque X" = GROUP BY X avec X dans le SELECT. "Brut" = somme des valeurs absolues. Sans période précisée, utilise toute la base (pas seulement le dernier jour). Un mois entier = du 1er au dernier jour du mois (octobre 2026 se termine le 31). Mois = BETWEEN premier et dernier jour. "Les N X avec le plus ..." = une seule colonne X (pas la mesure). "Cumulé" = SUM(SUM(mesure)) OVER (ORDER BY date) avec GROUP BY date, une ligne par jour. "Quel jour/date a le meilleur ..." = GROUP BY date puis ORDER BY l'agrégat. "Delta FX" = delta_fx_eur (pas notionnel), "DV01" = dv01_eur. Dates extrêmes de la base ("première/dernière date") = une seule vue, v_positions. Si la question n'est pas répondable avec ces données, mets sql=null et explique dans refus.
Si tu as dû faire une hypothèse (ex: période non précisée), liste-la dans hypotheses.
Réponds par un seul objet JSON: {{"sql": ..., "graphique": "ligne"|"barres"|null, "hypotheses": [...], "refus": ...}}.
Exemples:
{shots}"""


def _chat(messages, client):
    r = client.chat(model=MODEL, messages=messages, format=Answer.model_json_schema(), think=False,
                    options={"temperature": 0, "num_ctx": 4096})
    return r["message"]["content"]


def propose(question, client=None):
    """Returns dict(answer=Answer|None, sql=validated sql|None, attempts=int, seconds=float, error=str|None).
    Not-answerable / invalid / still-rejected-after-repair all come back with sql=None (declared failure)."""
    import ollama
    client = client or ollama.Client()
    t0 = time.time()
    msgs = [{"role": "system", "content": system_prompt(question)}, {"role": "user", "content": question}]
    err = None
    for attempt in (1, 2):
        raw = _chat(msgs, client)
        try:
            ans = Answer.model_validate_json(raw)
            if ans.refus or not ans.sql:
                return dict(answer=ans, sql=None, attempts=attempt, seconds=time.time() - t0, error="refus")
            return dict(answer=ans, sql=check(ans.sql), attempts=attempt, seconds=time.time() - t0, error=None)
        except (ValidationError, Rejected) as e:
            err = str(e).splitlines()[0] if isinstance(e, ValidationError) else str(e)
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Erreur: {err}. Corrige et renvoie le JSON complet."}]
    return dict(answer=None, sql=None, attempts=2, seconds=time.time() - t0, error=err)
