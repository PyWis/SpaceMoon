import csv
import io


def parse_questions_csv(csv_content: str) -> list:
    """Parse CSV and return list of question dicts.

    Expected columns: Domanda, Opzione_1..Opzione_5, Risposta_Corretta, Ruolo_Bonus
    """
    questions = []
    reader = csv.DictReader(io.StringIO(csv_content))

    for i, row in enumerate(reader, 1):
        text = row.get('Domanda', '').strip()
        if not text:
            continue

        options = []
        for j in range(1, 6):
            opt = row.get(f'Opzione_{j}', '').strip()
            if opt:
                options.append(opt)

        if len(options) < 3:
            continue

        correct_raw = row.get('Risposta_Corretta', '').strip()
        correct_idx = None

        # Try as 1-based integer index
        try:
            idx = int(correct_raw) - 1
            if 0 <= idx < len(options):
                correct_idx = idx
        except ValueError:
            # Try matching text
            for j, opt in enumerate(options):
                if opt.strip().lower() == correct_raw.lower():
                    correct_idx = j
                    break

        if correct_idx is None:
            continue

        bonus_role = row.get('Ruolo_Bonus', '').strip() or None
        if bonus_role:
            from app.models import ROLES
            if bonus_role not in ROLES:
                bonus_role = None

        questions.append({
            'text':           text,
            'options':        options,
            'correct_answer': correct_idx,
            'bonus_role':     bonus_role,
        })

    return questions
