"""
Seed Data — Initialize the dictionary with starter terms and admin user.

RUN THIS ONCE after setting up:
    python seed_data.py

It will:
1. Create the database tables
2. Add the admin user (you)
3. Load starter medical terms

You can run it multiple times safely — it checks for duplicates.
"""

from app import create_app
from models import db, Term, Admin

# ----- CONFIGURATION -----
# Change these before running!
ADMIN_USERNAME = "khris"
ADMIN_PASSWORD = "***REMOVED***"  # CHANGE THIS to something strong!

# ----- STARTER TERMS -----
# Replace and expand these with your real curated translations
STARTER_TERMS = [
    {
        "english": "Hypertension",
        "kinyarwanda": "Umuvuduko w'amaraso",
        "example_en": "The patient was diagnosed with hypertension.",
        "example_rw": "Umurwayi yasuzumwe afite umuvuduko w'amaraso.",
        "etymology": "'Umuvuduko' means pressure or force, 'w'amaraso' means of the blood. Together they literally describe 'pressure of the blood,' which maps directly to the medical concept of elevated blood pressure.",
        "category": "Cardiology",
    },
    {
        "english": "Diabetes",
        "kinyarwanda": "Diyabete / Indwara y'igisukari",
        "example_en": "Diabetes requires careful management of blood sugar levels.",
        "example_rw": "Diyabete isaba kwitaho neza urwego rw'isukari mu maraso.",
        "etymology": "'Indwara y'igisukari' literally translates to 'disease of sugar,' which accurately captures the core characteristic of diabetes — the body's inability to properly regulate sugar (glucose) in the blood.",
        "category": "Endocrinology",
    },
    {
        "english": "Malaria",
        "kinyarwanda": "Malariya",
        "example_en": "Malaria is transmitted through mosquito bites.",
        "example_rw": "Malariya ikwirakwizwa n'umubu.",
        "etymology": "The term 'Malariya' is a direct phonetic adaptation from the international medical term. It is universally understood in Rwandan health contexts and used consistently across clinical, community, and public health settings.",
        "category": "Infectious Disease",
    },
    {
        "english": "Vaccination",
        "kinyarwanda": "Ikingira",
        "example_en": "Vaccination is essential for preventing childhood diseases.",
        "example_rw": "Ikingira ni ngombwa mu gukinga indwara z'abana.",
        "etymology": "'Ikingira' comes from the verb 'gukingira' meaning 'to protect' or 'to shield.' This beautifully captures the preventive nature of vaccination — it is literally 'the protection.'",
        "category": "Public Health",
    },
    {
        "english": "Pregnancy",
        "kinyarwanda": "Gutwita / Inda",
        "example_en": "Regular check-ups during pregnancy are important.",
        "example_rw": "Gusuzumwa buri gihe mu gihe cy'inda ni ngombwa.",
        "etymology": "'Gutwita' is the verb meaning 'to be pregnant,' while 'inda' refers to the pregnancy itself (literally 'stomach/womb'). Both are widely used — 'inda' in everyday speech, 'gutwita' in more formal health contexts.",
        "category": "Maternal Health",
    },
    {
        "english": "Anemia",
        "kinyarwanda": "Kubura amaraso",
        "example_en": "Anemia can cause fatigue and weakness.",
        "example_rw": "Kubura amaraso bishobora gutera umunaniro n'intege nke.",
        "etymology": "'Kubura' means 'to lack' or 'to be deficient in,' and 'amaraso' means 'blood.' The literal meaning 'lacking blood' aligns precisely with the medical definition of anemia — a deficiency in red blood cells or hemoglobin.",
        "category": "Hematology",
    },
    {
        "english": "Omphalotomy",
        "kinyarwanda": "Kugenya",
        "example_en": "The midwife performed the omphalotomy immediately after delivery.",
        "example_rw": "Umubyaza yakoze kugenya ako kanya nyuma yo kubyara.",
        "etymology": "'Kugenya' refers specifically to the act of cutting and separating the umbilical cord between mother and baby during delivery. It maps precisely to the clinical term 'omphalotomy' (from Greek 'omphalos' — navel, and '-tomy' — cutting). This is one of the oldest and most fundamental surgical acts in human experience, and Kinyarwanda captures it with a dedicated verb rather than borrowing from medical Latin.",
        "category": "Obstetrics",
    },
    {
        "english": "Fever",
        "kinyarwanda": "Umuriro",
        "example_en": "The child has a high fever and should be taken to the clinic.",
        "example_rw": "Umwana afite umuriro ukomeye, agomba kujyanwa ku ivuriro.",
        "etymology": "'Umuriro' literally means 'fire.' This metaphor is powerful and universally understood — the body burning with elevated temperature. It is the standard term used across all healthcare settings in Rwanda.",
        "category": "General Medicine",
    },
    {
        "english": "Tuberculosis",
        "kinyarwanda": "Igituntu",
        "example_en": "Tuberculosis treatment requires a complete course of antibiotics.",
        "example_rw": "Kuvura igituntu bisaba gufata imiti yose nk'uko byateganyijwe.",
        "etymology": "'Igituntu' is the established Kinyarwanda term for tuberculosis, widely used in clinical and public health communication throughout Rwanda. It has no direct etymological decomposition but is the universally recognized standard term.",
        "category": "Infectious Disease",
    },
    {
        "english": "Diarrhea",
        "kinyarwanda": "Impiswi",
        "example_en": "Diarrhea in children can lead to severe dehydration.",
        "example_rw": "Impiswi mu bana zishobora gutera kubura amazi mu mubiri bikabije.",
        "etymology": "'Impiswi' is the standard Kinyarwanda term for diarrhea. It is used consistently across community health, clinical settings, and public health messaging in Rwanda.",
        "category": "Gastroenterology",
    },
]


def seed():
    app = create_app()
    with app.app_context():
        # Create tables
        db.create_all()

        # Create admin user if not exists
        existing_admin = Admin.query.filter_by(username=ADMIN_USERNAME).first()
        if not existing_admin:
            admin = Admin(username=ADMIN_USERNAME)
            admin.set_password(ADMIN_PASSWORD)
            db.session.add(admin)
            print(f"✓ Admin user '{ADMIN_USERNAME}' created")
        else:
            print(f"→ Admin user '{ADMIN_USERNAME}' already exists")

        # Add starter terms (skip duplicates)
        added = 0
        for term_data in STARTER_TERMS:
            existing = Term.query.filter_by(english=term_data["english"]).first()
            if not existing:
                term = Term(**term_data)
                db.session.add(term)
                added += 1

        db.session.commit()
        print(f"✓ Added {added} new terms ({len(STARTER_TERMS) - added} already existed)")
        print(f"\n  Total terms in dictionary: {Term.query.count()}")
        print(f"\n  ⚠  Remember to change the admin password in seed_data.py!")
        print(f"  ⚠  Admin login: /admin/login")


if __name__ == "__main__":
    seed()
