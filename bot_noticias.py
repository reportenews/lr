import os
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

# Intentar usar el SDK oficial de Google GenAI o fallback HTTP
try:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    HAS_GENAI = True
except Exception:
    HAS_GENAI = False

def redactar_noticia_con_ia(texto_original, localidad, autor):
    """Envía el contenido bruto de la red social a Gemini para generar titular y resumen periodístico."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        # Fallback sin IA si no está configurada la API key
        return {
            "title": f"Novedades en {localidad} vía {autor}",
            "summary": (texto_original[:200] + "...") if len(texto_original) > 200 else texto_original
        }

    prompt = f"""
    Eres el editor en jefe de un portal de noticias de la región de {localidad}.
    A partir de la siguiente publicación de la red social de '{autor}', genera una noticia breve con formato JSON estricto:
    1. 'title': Titular periodístico profesional, atractivo y conciso (máximo 12 palabras).
    2. 'summary': Resumen explicativo de 2 o 3 oraciones contextualizando lo que ocurrió para el lector.

    Publicación original:
    \"\"\"{texto_original}\"\"\"

    Responde ÚNICAMENTE un objeto JSON válido con los campos "title" y "summary". Sin bloques de código markdown.
    """

    try:
        if HAS_GENAI:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            raw = response.text.strip()
        else:
            # Petición REST directa a Gemini
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as res:
                data = json.loads(res.read().decode("utf-8"))
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Limpiar posibles delimitadores markdown ```json ... ```
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        print(f"Error al redactar con IA: {e}")
        return {
            "title": f"Actualización de {autor} en {localidad}",
            "summary": (texto_original[:220] + "...") if len(texto_original) > 220 else texto_original
        }

def extraer_telegram(channel_name):
    """Extrae las publicaciones recientes de la vista previa web de un canal público de Telegram."""
    posts = []
    url = f"[https://t.me/s/](https://t.me/s/){channel_name}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            # Extraer textos y enlaces de mensajes
            messages = re.findall(r'<div class="tgme_widget_message_text[^"]*">(.*?)</div>', html, re.DOTALL)
            links = re.findall(r'<a class="tgme_widget_message_date" href="([^"]+)"', html)
            
            for i in range(min(len(messages), len(links), 3)): # Últimos 3 mensajes
                texto_limpio = re.sub(r'<[^>]+>', ' ', messages[i]).strip()
                if len(texto_limpio) > 20:
                    posts.append({
                        "raw_text": texto_limpio,
                        "url": links[i]
                    })
    except Exception as e:
        print(f"Error al leer Telegram @{channel_name}: {e}")
    return posts

def extraer_youtube(channel_id):
    """Lee el feed RSS oficial y público de un canal de YouTube sin cuota de API."""
    videos = []
    url = f"[https://www.youtube.com/feeds/videos.xml?channel_id=](https://www.youtube.com/feeds/videos.xml?channel_id=){channel_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            ns = {'atom': '[http://www.w3.org/2005/Atom](http://www.w3.org/2005/Atom)', 'yt': '[http://www.youtube.com/xml/schemas/2015](http://www.youtube.com/xml/schemas/2015)'}
            
            for entry in root.findall('atom:entry', ns)[:2]:
                title = entry.find('atom:title', ns).text
                link = entry.find('atom:link', ns).attrib['href']
                summary_elem = entry.find('atom:summary', ns)
                desc = summary_elem.text if summary_elem is not None else title
                videos.append({
                    "raw_text": f"Video: {title}. Descripción: {desc}",
                    "url": link
                })
    except Exception as e:
        print(f"Error al leer YouTube {channel_id}: {e}")
    return videos

def procesar_todas_las_fuentes():
    if not os.path.exists("fuentes.json"):
        print("No se encontró fuentes.json")
        return

    with open("fuentes.json", "r", encoding="utf-8") as f:
        fuentes = json.load(f)

    noticias_finales = []

    for localidad, cuentas in fuentes.items():
        print(f"--- Procesando localidad: {localidad} ---")
        for cuenta in cuentas:
            platform = cuenta.get("platform")
            author = cuenta.get("author", "Redes Sociales")
            posts = []

            if platform == "telegram":
                posts = extraer_telegram(cuenta.get("channel"))
            elif platform == "youtube":
                posts = extraer_youtube(cuenta.get("channel_id"))

            for post in posts:
                print(f"Redactando con IA para {author}...")
                redaccion = redactar_noticia_con_ia(post["raw_text"], localidad, author)
                
                noticias_finales.append({
                    "id": f"auto-{len(noticias_finales) + 1}",
                    "place": localidad,
                    "platform": platform,
                    "title": redaccion.get("title", f"Novedad en {localidad}"),
                    "summary": redaccion.get("summary", post["raw_text"][:200]),
                    "author": author,
                    "url": post["url"],
                    "pubDate": datetime.now().strftime("%d/%m %H:%M")
                })

    # Guardar archivo compilado para el sitio web
    with open("noticias.json", "w", encoding="utf-8") as f:
        json.dump(noticias_finales, f, ensure_ascii=False, indent=2)

    print(f"¡Éxito! Se generaron {len(noticias_finales)} noticias automáticas en noticias.json.")

if __name__ == "__main__":
    procesar_todas_las_fuentes()