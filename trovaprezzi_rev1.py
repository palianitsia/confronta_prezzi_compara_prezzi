from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import time

# ============ VARIABILI GLOBALI ============
NOME_PRODOTTO = "NIDINA OPTIPRO 2 Latte di Proseguimento in Polvere da 6 Mesi Latta 800g"
PREZZO_AMAZON = 13.80
URL_BASE = "https://www.trovaprezzi.it"

INTESTAZIONI = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/jxl,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "it,it-IT;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Referer": "https://www.google.com/",
}


def normalizza(testo: str) -> str:
    testo = testo.lower()
    testo = re.sub(r"\s+", " ", testo)
    testo = re.sub(r"\s*([,/|])\s*", r"\1", testo)
    return testo.strip()


def riscaldamento(sessione):
    try:
        risposta = sessione.get(URL_BASE, headers=INTESTAZIONI, timeout=30)
        print(f"[riscaldamento] stato: {risposta.status_code}")
        if risposta.status_code == 403:
            print("[riscaldamento] ⚠️ 403: impronta TLS bloccata. Potrebbe servire un proxy residenziale italiano.")
            return False
        return True
    except Exception as errore:
        print(f"[riscaldamento] errore: {errore}")
        return False


def cerca_prodotto(sessione, query: str) -> str:
    url = f"{URL_BASE}/categoria.aspx?id=-1&libera={query}"
    try:
        risposta = sessione.get(url, headers=INTESTAZIONI, timeout=30, allow_redirects=True)
        print(f"[ricerca] stato: {risposta.status_code}, url finale: {risposta.url}")
        if risposta.status_code == 403:
            print("[ricerca] ⚠️ 403: richiesta bloccata da DataDome.")
            return ""
        return risposta.text
    except Exception as errore:
        print(f"[ricerca] errore: {errore}")
        return ""


def estrai_offerte(html: str, query: str):
    zuppa = BeautifulSoup(html, "html.parser")
    offerte = []
    query_normalizzata = normalizza(query)

    for elemento in zuppa.select("li.listing_item"):
        tag_nome = elemento.select_one(".item_name")
        if not tag_nome:
            continue

        nome_prodotto = tag_nome.get_text(strip=True)

        if query_normalizzata not in normalizza(nome_prodotto):
            continue

        tag_negozio = elemento.select_one(".merchant_name")
        tag_prezzo = elemento.select_one(".item_total_price")
        testo_prezzo = tag_prezzo.get_text(strip=True) if tag_prezzo else ""

        if "non disponibile" in testo_prezzo.lower() or not testo_prezzo:
            tag_prezzo = elemento.select_one(".item_basic_price")
            testo_prezzo = tag_prezzo.get_text(strip=True) if tag_prezzo else ""

        corrispondenza = re.search(r"([\d.]+,\d{2})", testo_prezzo)
        if not corrispondenza:
            continue

        prezzo = float(corrispondenza.group(1).replace(".", "").replace(",", "."))
        negozio = tag_negozio.get_text(strip=True) if tag_negozio else "Sconosciuto"

        offerte.append({
            "negozio": negozio,
            "prezzo": prezzo,
            "nome": nome_prodotto,
        })

    return offerte


def valuta(prezzo_amazon: float, offerte: list):
    if len(offerte) == 0:
        return {
            "verdetto": "NESSUN_DATO",
            "messaggio": "Nessuna offerta trovata con il nome corrispondente.",
        }

    offerte_ordinate = sorted(offerte, key=lambda x: x["prezzo"])

    if len(offerte) == 1:
        alternativa = offerte_ordinate[0]
        differenza = prezzo_amazon - alternativa["prezzo"]
        differenza_percentuale = (differenza / alternativa["prezzo"]) * 100
        if differenza < 0:
            relazione = f"Amazon costa {abs(differenza):.2f} € in meno"
        elif differenza > 0:
            relazione = f"Amazon costa {differenza:.2f} € in più"
        else:
            relazione = "prezzo identico"
        return {
            "verdetto": "CONFRONTO_SINGOLO",
            "messaggio": (
                f"Una sola offerta comparabile: {alternativa['negozio']} a €{alternativa['prezzo']:.2f}. "
                f"{relazione} ({differenza_percentuale:+.1f}%). "
                f"Nessuna mediana di mercato: confronto puramente indicativo."
            ),
            "prezzo_amazon": prezzo_amazon,
            "offerte": offerte_ordinate,
        }

    if len(offerte) == 2:
        media = sum(o["prezzo"] for o in offerte_ordinate) / 2
        differenza_percentuale = ((prezzo_amazon - media) / media) * 100
        return {
            "verdetto": "CONFRONTO_LIMITATO",
            "messaggio": (
                f"Due offerte comparabili (media €{media:.2f}, "
                f"Amazon {differenza_percentuale:+.1f}%). "
                f"Campione troppo piccolo per un verdetto affidabile."
            ),
            "prezzo_amazon": prezzo_amazon,
            "media": round(media, 2),
            "differenza_percentuale": round(differenza_percentuale, 1),
            "offerte": offerte_ordinate,
        }

    prezzi = [o["prezzo"] for o in offerte_ordinate]
    mediana = prezzi[len(prezzi) // 2] if len(prezzi) % 2 else (
        prezzi[len(prezzi) // 2 - 1] + prezzi[len(prezzi) // 2]
    ) / 2

    differenza_percentuale = ((prezzo_amazon - mediana) / mediana) * 100

    if differenza_percentuale <= -10:
        verdetto = "OTTIMO_AFFARE"
    elif differenza_percentuale <= 5:
        verdetto = "NELLA_MEDIA"
    else:
        verdetto = "CARO"

    return {
        "verdetto": verdetto,
        "prezzo_amazon": prezzo_amazon,
        "mediana": round(mediana, 2),
        "minimo": round(min(prezzi), 2),
        "massimo": round(max(prezzi), 2),
        "differenza_percentuale": round(differenza_percentuale, 1),
        "migliori_offerte": offerte_ordinate[:10],
    }


def principale():
    sessione = requests.Session(impersonate="chrome")

    if not riscaldamento(sessione):
        print("Riscaldamento fallito, interruzione.")
        return

    time.sleep(2)

    html = cerca_prodotto(sessione, NOME_PRODOTTO)
    if not html:
        print("Nessun HTML ricevuto, interruzione.")
        return

    offerte = estrai_offerte(html, NOME_PRODOTTO)
    print(f"\nOfferte valide trovate (nome corrispondente): {len(offerte)}")
    for offerta in sorted(offerte, key=lambda x: x["prezzo"]):
        print(f"  - {offerta['negozio']}: €{offerta['prezzo']:.2f}  [{offerta['nome'][:60]}...]")

    risultato = valuta(PREZZO_AMAZON, offerte)
    print("\n" + "=" * 50)
    print(f"VERDETTO: {risultato['verdetto']}")
    print(risultato["messaggio"])

    if risultato["verdetto"] in ("OTTIMO_AFFARE", "NELLA_MEDIA", "CARO"):
        print(f"\nPrezzo Amazon: €{risultato['prezzo_amazon']:.2f}")
        print(f"Mediana altri negozi: €{risultato['mediana']:.2f}")
        print(f"Minimo: €{risultato['minimo']:.2f} | Massimo: €{risultato['massimo']:.2f}")
        print(f"Differenza vs mediana: {risultato['differenza_percentuale']:+.1f}%")
        print("\nPrime 10 offerte:")
        for indice, offerta in enumerate(risultato["migliori_offerte"], 1):
            print(f"  {indice}. {offerta['negozio']}: €{offerta['prezzo']:.2f}")


if __name__ == "__main__":
    principale()
