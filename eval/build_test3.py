"""Builds eval/test3.json: 60 fresh questions written AFTER the prompt was changed for the test v2 failures and BEFORE it ever saw them.
Test v2 is now burned for tuning (its pairs feed the few-shot pool); v3 is the number to quote.
Scoring rule fixed BEFORE the v3 run: strict (headline) and lenient (reference columns are a subset of the returned columns), both reported.
sha256 in eval/TEST3_SHA256. No reference SQL may equal (normalised) any earlier SQL."""
import hashlib
import json
import sys
sys.path.insert(0, "src")
from risksql import executor
from build_sets import q, mr, norm, DEV, TEST

LV = lambda t: f"(SELECT max(date) FROM {t})"
P = "v_positions"
RB = "v_risque_book"

T3 = [
    q("Quelle était la VaR du book FX_SPOT le 8 octobre 2026 ?", f"SELECT var99_1j_eur FROM {RB} WHERE book='FX_SPOT' AND date=DATE '2026-10-08'"),
    q("Dernière ES du book FX_SPOT ?", f"SELECT es975_1j_eur FROM {RB} WHERE book='FX_SPOT' AND date={LV(RB)}"),
    q("Combien a gagné le trader Petit en septembre 2026 ?", f"SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Petit' AND {mr('2026-09')}"),
    q("P&L du book TAUX_EUR en août 2026", f"SELECT sum(pnl_eur) FROM v_pnl WHERE book='TAUX_EUR' AND {mr('2026-08')}"),
    q("P&L total du desk Change en octobre 2026", f"SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Change' AND {mr('2026-10')}"),
    q("Quels sont les 2 traders avec le meilleur P&L total ?", "SELECT trader FROM v_pnl GROUP BY trader ORDER BY sum(pnl_eur) DESC LIMIT 2", True),
    q("Donne les 3 books les plus risqués en VaR au dernier jour", f"SELECT book FROM {RB} WHERE date={LV(RB)} ORDER BY var99_1j_eur DESC LIMIT 3", True),
    q("Combien de fois le book TAUX_EUR a-t-il dépassé 60 % de sa limite ?", "SELECT count(*) FROM v_limites WHERE book='TAUX_EUR' AND utilisation_pct>60"),
    q("Combien de jours a-t-on observé un dépassement de VaR sur au moins un book ?", f"SELECT count(DISTINCT date) FROM {RB} WHERE depassement_var"),
    q("À quelles dates le book TAUX_EUR a-t-il dépassé sa VaR ?", f"SELECT date FROM {RB} WHERE book='TAUX_EUR' AND depassement_var"),
    q("Pire P&L journalier du book FX_SPOT ?", f"SELECT min(pnl_eur) FROM {RB} WHERE book='FX_SPOT'"),
    q("Meilleur P&L journalier du book TAUX_EUR ?", f"SELECT max(pnl_eur) FROM {RB} WHERE book='TAUX_EUR'"),
    q("Combien de positions pour le trader Bernard au dernier jour ?", f"SELECT count(DISTINCT position_id) FROM {P} WHERE trader='Bernard' AND date={LV(P)}"),
    q("Nombre de positions par trader au dernier jour ?", f"SELECT trader, count(*) FROM {P} WHERE date={LV(P)} GROUP BY trader"),
    q("Notionnel net total en USD au dernier jour ?", f"SELECT sum(notionnel) FROM {P} WHERE devise='USD' AND date={LV(P)}"),
    q("Notionnel brut du book TAUX_USD au dernier jour ?", f"SELECT sum(abs(notionnel)) FROM {P} WHERE book='TAUX_USD' AND date={LV(P)}"),
    q("DV01 net du book FX_SPOT au dernier jour ?", f"SELECT sum(dv01_eur) FROM {P} WHERE book='FX_SPOT' AND date={LV(P)}"),
    q("DV01 net par book au dernier jour ?", f"SELECT book, sum(dv01_eur) FROM {P} WHERE date={LV(P)} GROUP BY book"),
    q("Quel book a le plus gros notionnel brut au dernier jour ?", f"SELECT book FROM {P} WHERE date={LV(P)} GROUP BY book ORDER BY sum(abs(notionnel)) DESC LIMIT 1", True),
    q("Quel desk a le plus gros DV01 net au dernier jour ?", f"SELECT desk FROM {P} WHERE date={LV(P)} GROUP BY desk ORDER BY sum(dv01_eur) DESC LIMIT 1", True),
    q("Quel desk a le pire P&L total ?", "SELECT desk FROM v_pnl GROUP BY desk ORDER BY sum(pnl_eur) LIMIT 1", True),
    q("VaR minimale par book ?", f"SELECT book, min(var99_1j_eur) FROM {RB} GROUP BY book"),
    q("ES moyenne du book TAUX_USD ?", f"SELECT avg(es975_1j_eur) FROM {RB} WHERE book='TAUX_USD'"),
    q("Utilisation moyenne de la limite du book FX_SPOT ?", "SELECT avg(utilisation_pct) FROM v_limites WHERE book='FX_SPOT'"),
    q("Quels books ont une VaR moyenne supérieure à 300000 ?", f"SELECT book FROM {RB} GROUP BY book HAVING avg(var99_1j_eur)>300000"),
    q("Quels books ont dépassé 86 % de leur limite au moins une fois ?", "SELECT DISTINCT book FROM v_limites WHERE utilisation_pct>86"),
    q("Quel jour la VaR du book FX_SPOT était-elle la plus haute ?", f"SELECT date FROM {RB} WHERE book='FX_SPOT' ORDER BY var99_1j_eur DESC, date LIMIT 1", True),
    q("Quel jour le P&L du desk Change a-t-il été le pire ?", "SELECT date FROM v_pnl WHERE desk='Change' GROUP BY date ORDER BY sum(pnl_eur) LIMIT 1", True),
    q("Quel jour le P&L du book TAUX_EUR a-t-il été le meilleur ?", f"SELECT date FROM {RB} WHERE book='TAUX_EUR' ORDER BY pnl_eur DESC, date LIMIT 1", True),
    q("P&L du desk Taux par mois", "SELECT strftime(date,'%Y-%m') AS mois, sum(pnl_eur) FROM v_pnl WHERE desk='Taux' GROUP BY 1 ORDER BY 1", True, "chart"),
    q("Évolution de l'ES du book TAUX_EUR sur les 30 derniers jours", f"SELECT date, es975_1j_eur FROM {RB} WHERE book='TAUX_EUR' AND date>DATE '2026-10-30'-INTERVAL 30 DAY ORDER BY date", True, "chart"),
    q("Évolution du taux USD 5Y sur les 90 derniers jours", "SELECT date, valeur FROM v_marche WHERE serie='USD_5Y' AND date>DATE '2026-10-30'-INTERVAL 90 DAY ORDER BY date", True, "chart"),
    q("Courbe du P&L cumulé du desk Taux en octobre 2026", f"SELECT date, sum(sum(pnl_eur)) OVER (ORDER BY date) AS cum FROM v_pnl WHERE desk='Taux' AND {mr('2026-10')} GROUP BY date ORDER BY date", True, "chart"),
    q("Combien de traders dans le desk Change ?", f"SELECT count(DISTINCT trader) FROM {P} WHERE desk='Change'"),
    q("Liste des traders du book TAUX_EUR", f"SELECT DISTINCT trader FROM {P} WHERE book='TAUX_EUR'"),
    q("Quelles devises sont présentes dans le book FX_SPOT ?", f"SELECT DISTINCT devise FROM {P} WHERE book='FX_SPOT'"),
    q("Quelle est la dernière date de la base ?", f"SELECT max(date) FROM {P}"),
    q("Combien de jours ouvrés en septembre 2026 ?", f"SELECT count(DISTINCT date) FROM v_pnl WHERE {mr('2026-09')}"),
    q("Taux USD 2Y au dernier jour ?", f"SELECT valeur FROM v_marche WHERE serie='USD_2Y' AND date={LV('v_marche')}"),
    q("Taux USD 2Y moyen en octobre 2026 ?", f"SELECT avg(valeur) FROM v_marche WHERE serie='USD_2Y' AND {mr('2026-10')}"),
    q("Taux EUR 10Y minimum sur la période ?", "SELECT min(valeur) FROM v_marche WHERE serie='EUR_10Y'"),
    q("Taux EUR 5Y maximum sur la période ?", "SELECT max(valeur) FROM v_marche WHERE serie='EUR_5Y'"),
    q("Pente 10Y-2Y EUR le 20 octobre 2026 ?", "SELECT (SELECT valeur FROM v_marche WHERE serie='EUR_10Y' AND date=DATE '2026-10-20')-(SELECT valeur FROM v_marche WHERE serie='EUR_2Y' AND date=DATE '2026-10-20')"),
    q("Pente 10Y-5Y USD au dernier jour ?", f"SELECT (SELECT valeur FROM v_marche WHERE serie='USD_10Y' AND date={LV('v_marche')})-(SELECT valeur FROM v_marche WHERE serie='USD_5Y' AND date={LV('v_marche')})"),
    q("Écart de P&L entre le trader Thomas et le trader Bernard sur toute la période", "SELECT (SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Thomas')-(SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Bernard')"),
    q("Part du P&L total due au book FX_SPOT", "SELECT (SELECT sum(pnl_eur) FROM v_pnl WHERE book='FX_SPOT')/(SELECT sum(pnl_eur) FROM v_pnl)"),
    q("Écart-type de l'ES du book TAUX_USD ?", f"SELECT stddev_samp(es975_1j_eur) FROM {RB} WHERE book='TAUX_USD'"),
    q("Médiane de la VaR du book TAUX_EUR ?", f"SELECT median(var99_1j_eur) FROM {RB} WHERE book='TAUX_EUR'"),
    q("Combien de jours le P&L du book FX_SPOT a-t-il été négatif ?", f"SELECT count(*) FROM {RB} WHERE book='FX_SPOT' AND pnl_eur<0"),
    q("Classe les desks par P&L total décroissant", "SELECT desk, sum(pnl_eur) FROM v_pnl GROUP BY desk ORDER BY sum(pnl_eur) DESC", True),
    q("Classe les books par ES moyenne croissante", f"SELECT book, avg(es975_1j_eur) FROM {RB} GROUP BY book ORDER BY avg(es975_1j_eur)", True),
    q("ES du book TAUX_USD le 25 septembre 2026 ?", f"SELECT es975_1j_eur FROM {RB} WHERE book='TAUX_USD' AND date=DATE '2026-09-25'"),
    q("Utilisation de limite de FX_SPOT le 14 octobre 2026 ?", "SELECT utilisation_pct FROM v_limites WHERE book='FX_SPOT' AND date=DATE '2026-10-14'"),
    q("Delta FX total par book au dernier jour ?", f"SELECT book, sum(delta_fx_eur) FROM {P} WHERE date={LV(P)} GROUP BY book"),
    q("Delta FX du trader Dubois au dernier jour ?", f"SELECT sum(delta_fx_eur) FROM {P} WHERE trader='Dubois' AND date={LV(P)}"),
    q("VaR moyenne en octobre 2026 par book", f"SELECT book, avg(var99_1j_eur) FROM {RB} WHERE {mr('2026-10')} GROUP BY book"),
    q("Nombre de positions short (notionnel négatif) du desk Taux au dernier jour ?", f"SELECT count(*) FROM {P} WHERE desk='Taux' AND notionnel<0 AND date={LV(P)}"),
    q("Notionnel de la plus grosse position short du book TAUX_EUR au dernier jour ?", f"SELECT min(notionnel) FROM {P} WHERE book='TAUX_EUR' AND date={LV(P)}"),
    q("Quel trader a le plus gros delta FX absolu au dernier jour ?", f"SELECT trader FROM {P} WHERE date={LV(P)} GROUP BY trader ORDER BY sum(abs(delta_fx_eur)) DESC LIMIT 1", True),
    q("Combien de jours la VaR du book TAUX_USD a-t-elle dépassé 200000 ?", f"SELECT count(*) FROM {RB} WHERE book='TAUX_USD' AND var99_1j_eur>200000"),
]
assert len(T3) == 60, len(T3)


con = executor.connect("data/risk.duckdb")
prev = [it for sp in ("dev", "test", "test2") for it in json.load(open(f"eval/{sp}.json", encoding="utf8"))] if False else DEV + TEST + json.load(open("eval/test2.json", encoding="utf8"))
seen = {norm(x.get("sql") or x["reference_sql"]) for x in prev}
items = []
dups = []
for i, it in enumerate(T3, 1):
    _, df = executor.run(con, it["sql"])
    assert len(df) > 0, (i, it["question"], "empty result")
    if norm(it["sql"]) in seen:
        dups.append((i, it["question"]))
        continue
    items.append(dict(id=f"V{i:02d}", question=it["question"], reference_sql=it["sql"], ordered=it["ordered"], kind=it["kind"]))
assert not dups, dups
ov = {x["question"] for x in items} & {x.get("question") for x in prev}
assert not ov, ov
json.dump(items, open("eval/test3.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
open("eval/TEST3_SHA256", "w").write(hashlib.sha256(open("eval/test3.json", "rb").read()).hexdigest() + "\n")
print(len(items), "questions written")
