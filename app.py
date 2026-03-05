"""
Islamic Companion App — Flask Backend
Proxies AlAdhan API for prayer times, Hijri dates, and Ramadan timetables.
Optional Google Gemini integration for AI-verified Hijri dates.

Usage:
    pip install -r requirements.txt
    python app.py
"""
import os
import json
from datetime import datetime, date

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

ALADHAN_BASE = "https://api.aladhan.com/v1"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ─── Helpers ────────────────────────────────────────────

def aladhan_get(path, params=None):
    """GET from AlAdhan API with error handling."""
    url = f"{ALADHAN_BASE}{path}"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def gemini_verify_hijri(aladhan_hijri, city="Mumbai"):
    """
    Use Gemini to verify/enhance a Hijri date from AlAdhan.
    Returns analysis dict or None if Gemini unavailable.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_key_here":
        return None

    try:
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""You are an Islamic date verification expert.
The AlAdhan API calculated today's Hijri date as: {aladhan_hijri['day']} {aladhan_hijri['month']['en']} {aladhan_hijri['year']} AH
City: {city}, India
Today's Gregorian date: {date.today().strftime('%d %B %Y')}

Please verify this Hijri date. Respond in this exact JSON format only:
{{
    "verified_hijri_date": "DD MonthName YYYY AH",
    "confidence": "high" or "medium" or "low",
    "note": "brief explanation",
    "regional_note": "any moon sighting info for this region"
}}"""

        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                http_options=genai_types.HttpOptions(timeout=8000),
            ),
        )
        text = response.text.strip()
        # Extract JSON from response
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        app.logger.warning(f"Gemini verification failed: {e}")
        return None


def gemini_islamic_context(hijri_date_str, city="Mumbai"):
    """
    Use Gemini to provide Islamic context for a date.
    Returns context dict or None.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_key_here":
        return None

    try:
        from google import genai
        from google.genai import types as genai_types
        client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""You are an Islamic calendar expert.
For the Hijri date: {hijri_date_str}
City: {city}, India

Provide Islamic context. Respond in this exact JSON format only:
{{
    "islamic_significance": "significance of this date or general info",
    "upcoming_events": ["list of upcoming Islamic events within 30 days"],
    "fasting_recommended": true/false,
    "special_nights": "any special night info or empty string"
}}"""

        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                http_options=genai_types.HttpOptions(timeout=8000),
            ),
        )
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        app.logger.warning(f"Gemini context failed: {e}")
        return None


# ─── Prayer Times ───────────────────────────────────────

@app.route("/api/prayer/city")
def prayer_by_city():
    """GET /api/prayer/city?city=Mumbai&country=India&method=1&school=1"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    method = request.args.get("method", "1")
    school = request.args.get("school", "1")

    today = date.today()
    try:
        data = aladhan_get("/timingsByCity", {
            "city": city,
            "country": country,
            "method": method,
            "school": school,
            "date_or_timestamp": today.strftime("%d-%m-%Y"),
        })
        timings = data["data"]["timings"]
        return jsonify({
            "data": {
                "prayer_times": {
                    "Fajr": timings.get("Fajr", ""),
                    "Sunrise": timings.get("Sunrise", ""),
                    "Dhuhr": timings.get("Dhuhr", ""),
                    "Asr": timings.get("Asr", ""),
                    "Maghrib": timings.get("Maghrib", ""),
                    "Isha": timings.get("Isha", ""),
                    "Imsak": timings.get("Imsak", ""),
                    "Midnight": timings.get("Midnight", ""),
                },
                "date": data["data"].get("date", {}),
                "meta": data["data"].get("meta", {}),
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/prayer/coords")
def prayer_by_coords():
    """GET /api/prayer/coords?lat=19.076&lon=72.877&method=1&school=1"""
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    method = request.args.get("method", "1")
    school = request.args.get("school", "1")

    if not lat or not lon:
        return jsonify({"error": "lat and lon are required"}), 400

    today = date.today()
    try:
        data = aladhan_get(f"/timings/{today.strftime('%d-%m-%Y')}", {
            "latitude": lat,
            "longitude": lon,
            "method": method,
            "school": school,
        })
        timings = data["data"]["timings"]
        return jsonify({
            "data": {
                "prayer_times": {
                    "Fajr": timings.get("Fajr", ""),
                    "Sunrise": timings.get("Sunrise", ""),
                    "Dhuhr": timings.get("Dhuhr", ""),
                    "Asr": timings.get("Asr", ""),
                    "Maghrib": timings.get("Maghrib", ""),
                    "Isha": timings.get("Isha", ""),
                    "Imsak": timings.get("Imsak", ""),
                    "Midnight": timings.get("Midnight", ""),
                },
                "date": data["data"].get("date", {}),
                "meta": data["data"].get("meta", {}),
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Hijri Dates ────────────────────────────────────────

@app.route("/api/hijri/today")
def hijri_today():
    """GET /api/hijri/today?city=Mumbai&country=India"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")

    today = date.today()
    try:
        # Get base Hijri date from AlAdhan
        data = aladhan_get("/timingsByCity", {
            "city": city,
            "country": country,
            "method": "1",
            "date_or_timestamp": today.strftime("%d-%m-%Y"),
        })
        hijri = data["data"]["date"]["hijri"]
        aladhan_hijri = {
            "day": hijri["day"],
            "month": {"en": hijri["month"]["en"], "ar": hijri["month"]["ar"]},
            "year": hijri["year"],
        }

        # Gemini verification (optional)
        gemini_analysis = gemini_verify_hijri(aladhan_hijri, city)
        hijri_str = f"{aladhan_hijri['day']} {aladhan_hijri['month']['en']} {aladhan_hijri['year']}"
        islamic_context = gemini_islamic_context(hijri_str, city)

        result = {
            "data": {
                "hijri_date": {
                    "aladhan": aladhan_hijri,
                    "gemini_verified": {
                        "gemini_analysis": gemini_analysis
                    } if gemini_analysis else None,
                },
                "islamic_context": {
                    "data": islamic_context
                } if islamic_context else None,
            }
        }
        return jsonify(result)
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hijri/to-hijri")
def gregorian_to_hijri():
    """GET /api/hijri/to-hijri?date=06-03-2026&city=Mumbai&enhance=true"""
    date_str = request.args.get("date")  # DD-MM-YYYY
    city = request.args.get("city", "Mumbai")
    enhance = request.args.get("enhance", "true").lower() == "true"

    if not date_str:
        return jsonify({"error": "date parameter required (DD-MM-YYYY)"}), 400

    try:
        data = aladhan_get(f"/gToH/{date_str}")
        hijri = data["data"]["hijri"]
        aladhan_hijri = {
            "day": hijri["day"],
            "month": {"en": hijri["month"]["en"], "ar": hijri["month"]["ar"]},
            "year": hijri["year"],
        }

        gemini_analysis = None
        if enhance:
            gemini_analysis = gemini_verify_hijri(aladhan_hijri, city)

        return jsonify({
            "data": {
                "hijri_date": {
                    "aladhan": aladhan_hijri,
                    "gemini_verified": {
                        "gemini_analysis": gemini_analysis
                    } if gemini_analysis else None,
                }
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hijri/to-gregorian")
def hijri_to_gregorian():
    """GET /api/hijri/to-gregorian?date=10-09-1447"""
    date_str = request.args.get("date")  # DD-MM-YYYY (Hijri)

    if not date_str:
        return jsonify({"error": "date parameter required (DD-MM-YYYY Hijri)"}), 400

    try:
        data = aladhan_get(f"/hToG/{date_str}")
        greg = data["data"]["gregorian"]
        return jsonify({
            "data": {
                "gregorian": {
                    "date": greg.get("date", ""),
                    "day": greg.get("day", ""),
                    "month": {
                        "en": greg["month"]["en"],
                        "number": greg["month"]["number"],
                    },
                    "year": greg.get("year", ""),
                    "weekday": {"en": greg["weekday"]["en"]},
                }
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Ramadan ────────────────────────────────────────────

@app.route("/api/ramadan/timetable")
def ramadan_timetable():
    """GET /api/ramadan/timetable?city=Mumbai&country=India&year=1447"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    hijri_year = request.args.get("year", "1447")

    try:
        # Ramadan is month 9 in Hijri calendar
        data = aladhan_get("/hijriCalendarByCity", {
            "city": city,
            "country": country,
            "month": "9",
            "year": hijri_year,
            "method": "1",
            "school": "1",
        })

        days = data.get("data", [])
        timetable = []

        for day in days:
            timings = day.get("timings", {})
            hijri = day.get("date", {}).get("hijri", {})
            greg = day.get("date", {}).get("gregorian", {})

            # Clean time strings (remove timezone parens)
            def clean(t):
                return t.split(" (")[0] if " (" in t else t

            timetable.append({
                "gregorian": greg.get("date", ""),
                "hijri": f"{hijri.get('day', '')} {hijri.get('month', {}).get('en', 'Ramadan')} {hijri.get('year', '')}",
                "sehri_ends": clean(timings.get("Imsak", "")),
                "fajr": clean(timings.get("Fajr", "")),
                "iftar": clean(timings.get("Maghrib", "")),
                "isha": clean(timings.get("Isha", "")),
            })

        return jsonify({
            "data": {
                "total_days": len(timetable),
                "timetable": timetable,
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ramadan/today-fast")
def today_fast():
    """GET /api/ramadan/today-fast?city=Mumbai&country=India"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")

    today = date.today()
    try:
        # Get today's date info including Hijri
        data = aladhan_get("/timingsByCity", {
            "city": city,
            "country": country,
            "method": "1",
            "school": "1",
            "date_or_timestamp": today.strftime("%d-%m-%Y"),
        })

        hijri = data["data"]["date"]["hijri"]
        hijri_month = int(hijri["month"]["number"])
        timings = data["data"]["timings"]

        def clean(t):
            return t.split(" (")[0] if " (" in t else t

        is_ramadan = hijri_month == 9

        result = {
            "data": {
                "is_ramadan": is_ramadan,
                "fasting_today": is_ramadan,
                "sehri_end": clean(timings.get("Imsak", "")),
                "iftar_time": clean(timings.get("Maghrib", "")),
            }
        }

        if not is_ramadan:
            # Calculate approximate days until next Ramadan
            # Hijri months: if current month < 9, days = (9 - month) * 29.5
            # If current month >= 9, days = (12 - month + 9) * 29.5
            current_day = int(hijri["day"])
            if hijri_month < 9:
                months_remaining = 9 - hijri_month
                days_in_current_month = 30 - current_day
                approx_days = days_in_current_month + int((months_remaining - 1) * 29.5)
            else:
                months_remaining = 12 - hijri_month + 9
                days_in_current_month = 30 - current_day
                approx_days = days_in_current_month + int((months_remaining - 1) * 29.5)

            result["data"]["next_ramadan_in_days"] = max(approx_days, 1)
            result["data"]["message"] = f"Ramadan is approximately {max(approx_days, 1)} days away. May Allah bless your patience."

        return jsonify(result)
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Sehri & Iftar (Any Month) ──────────────────────────

@app.route("/api/sehri-iftar/monthly")
def sehri_iftar_monthly():
    """GET /api/sehri-iftar/monthly?city=Mumbai&country=India&month=3&year=2026
    Returns Sehri (Imsak) and Iftar (Maghrib) for every day of a Gregorian month."""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    month = request.args.get("month", str(date.today().month))
    year = request.args.get("year", str(date.today().year))
    method = request.args.get("method", "1")
    school = request.args.get("school", "1")

    try:
        data = aladhan_get("/calendarByCity", {
            "city": city,
            "country": country,
            "month": month,
            "year": year,
            "method": method,
            "school": school,
        })

        days = data.get("data", [])
        timetable = []

        for day in days:
            timings = day.get("timings", {})
            hijri = day.get("date", {}).get("hijri", {})
            greg = day.get("date", {}).get("gregorian", {})

            def clean(t):
                return t.split(" (")[0] if " (" in t else t

            timetable.append({
                "gregorian": greg.get("date", ""),
                "weekday": greg.get("weekday", {}).get("en", ""),
                "hijri": f"{hijri.get('day', '')} {hijri.get('month', {}).get('en', '')} {hijri.get('year', '')}",
                "hijri_month": int(hijri.get("month", {}).get("number", 0)),
                "sehri_ends": clean(timings.get("Imsak", "")),
                "fajr": clean(timings.get("Fajr", "")),
                "iftar": clean(timings.get("Maghrib", "")),
                "isha": clean(timings.get("Isha", "")),
            })

        return jsonify({
            "data": {
                "city": city,
                "month": int(month),
                "year": int(year),
                "total_days": len(timetable),
                "timetable": timetable,
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Health ─────────────────────────────────────────────

@app.route("/")
def health():
    return jsonify({
        "status": "running",
        "name": "Islamic Companion API",
        "version": "1.1.0",
        "endpoints": [
            "/api/prayer/city",
            "/api/prayer/coords",
            "/api/hijri/today",
            "/api/hijri/to-hijri",
            "/api/hijri/to-gregorian",
            "/api/ramadan/timetable",
            "/api/ramadan/today-fast",
            "/api/sehri-iftar/monthly",
            "/ping",
        ],
        "gemini_enabled": bool(GEMINI_API_KEY and GEMINI_API_KEY != "your_key_here"),
    })


@app.route("/ping")
def ping():
    """Simple ping endpoint for cron jobs (e.g., cron-job.org) to keep the server awake."""
    return jsonify({"status": "alive", "timestamp": str(datetime.now())}), 200


if __name__ == "__main__":
    port = 5000
    print("🕌 Islamic Companion API starting...")
    print(f"   Gemini AI: {'✅ Enabled' if GEMINI_API_KEY and GEMINI_API_KEY != 'your_key_here' else '❌ Disabled (set GEMINI_API_KEY in .env)'}")
    print(f"   Server: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
