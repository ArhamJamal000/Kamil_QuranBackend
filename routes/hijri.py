from flask import Blueprint, jsonify, request
import requests
import google.generativeai as genai
from datetime import datetime
import os

hijri_bp = Blueprint('hijri', __name__)

@hijri_bp.route('/api/hijri-date')
def get_hijri_date():
    source = request.args.get('source', 'aladhan')  # default: aladhan
    today = datetime.now()
    day = today.day
    month = today.month
    year = today.year

    if source == 'aladhan':
        # AlAdhan API — existing integration
        url = f"https://api.aladhan.com/v1/gToH/{day}-{month}-{year}"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            hijri = data['data']['hijri']
            hijri_date_str = f"{hijri['day']} {hijri['month']['en']} {hijri['year']} AH"
            return jsonify({"hijri_date": hijri_date_str, "source": "aladhan"})
        except Exception as e:
            return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502

    elif source == 'gemini':
        # Gemini AI — verify Hijri date with India moon-sighting awareness
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            # Fallback to checking GEMINI_API_KEYS if multiple keys are used
            api_keys_env = os.getenv("GEMINI_API_KEYS", "")
            if api_keys_env:
                api_key = [k.strip() for k in api_keys_env.split(",") if k.strip()][0]

        if not api_key:
            return jsonify({"error": "Gemini API key not configured"}), 500

        try:
            genai.configure(api_key=api_key)
            prompt = (
                f"Today's Gregorian date is {day}/{month}/{year}. "
                f"What is today's Hijri (Islamic) date, taking into account India's moon-sighting conventions "
                f"(Rukyat-e-Hilal Committee)? "
                f"Reply ONLY in this exact format: DD MonthName YYYY AH "
                f"Example: 15 Ramadan 1446 AH"
            )
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            hijri_date_str = response.text.strip()
            return jsonify({"hijri_date": hijri_date_str, "source": "gemini"})
        except Exception as e:
            return jsonify({"error": f"Gemini API error: {str(e)}"}), 500

    return jsonify({"error": "Invalid source"}), 400
