# ==============================================================================
# LinguaMedica RW — Medical Dictionary Data
# Copyright (c) 2026 Christophe Mumaragishyika
#
# This data is licensed under Creative Commons Attribution 4.0 International
# (CC BY 4.0). See LICENSE-DATA for details.
# You must provide attribution if you reuse these translations.
#
# The application code is licensed separately under MIT. See LICENSE.
# ==============================================================================

"""
LinguaMedica RW — Seed Data
Run: python seed_data.py

It will:
1. Create the database tables
2. Add the admin user (you)
3. Load all medical terms (skips duplicates)

Safe to run multiple times — checks for existing terms by English name.
"""

from app import create_app
from models import db, Term, Admin
import os

# ------ CONFIGURATION ------
# Both loaded from environment variables — never hardcode credentials
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme-set-env-var")

# ------ ALL TERMS ------
STARTER_TERMS = [
    # =================================================================
    # ORIGINAL STARTER TERMS (10 terms)
    # =================================================================
    {
        "english": "Hypertension",
        "kinyarwanda": "Umuvuduko w'amaraso",
        "example_en": "The patient was diagnosed with hypertension.",
        "example_rw": "Umurwayi yasuzumwe afite umuvuduko w'amaraso.",
        "etymology": "'Umuvuduko' means pressure or force, 'w'amaraso' means of the blood — literally 'pressure of the blood.'",
        "category": "Cardiology",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Diabetes",
        "kinyarwanda": "Diyabete / Indwara y'igisukari",
        "example_en": "Diabetes requires careful management of blood sugar levels.",
        "example_rw": "Diyabete isaba kwitaho neza urwego rw'isukari mu maraso.",
        "etymology": "'Indwara y'igisukari' literally translates to 'disease of sugar,' which accurately captures the core characteristic of diabetes — the body's inability to regulate blood sugar.",
        "category": "Endocrinology",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Malaria",
        "kinyarwanda": "Malariya",
        "example_en": "Malaria is transmitted through mosquito bites.",
        "example_rw": "Malariya ikwirakwizwa n'umubu.",
        "etymology": "The term 'Malariya' is a direct phonetic adaptation from the international medical term. It is universally understood in Rwandan health contexts.",
        "category": "Infectious Disease",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Vaccination",
        "kinyarwanda": "Ikingira",
        "example_en": "Vaccination is essential for preventing childhood diseases.",
        "example_rw": "Ikingira ni ngombwa mu gukinga indwara z'abana.",
        "etymology": "From 'gukingira' meaning 'to protect' — literally 'the protection.' The word captures the preventive essence of vaccination.",
        "category": "Public Health",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Pregnancy",
        "kinyarwanda": "Gutwita / Inda",
        "example_en": "Regular check-ups during pregnancy are important.",
        "example_rw": "Gusuzumwa buri gihe mu gihe cy'inda ni ngombwa.",
        "etymology": "'Gutwita' is the verb 'to be pregnant,' while 'inda' refers to the pregnancy or the womb itself. Both are used interchangeably depending on context.",
        "category": "Maternal Health",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Anemia",
        "kinyarwanda": "Kubura amaraso",
        "example_en": "Anemia can cause fatigue and weakness.",
        "example_rw": "Kubura amaraso bishobora gutera umunaniro n'intege nke.",
        "etymology": "'Kubura' means 'to lack,' 'amaraso' means 'blood' — literally 'lacking blood.' This descriptive translation immediately communicates the condition to patients.",
        "category": "Hematology",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Omphalotomy",
        "kinyarwanda": "Kugenya",
        "example_en": "The midwife performed the omphalotomy immediately after delivery.",
        "example_rw": "Umubyaza yakoze kugenya ako kanya nyuma yo kubyara.",
        "etymology": "'Kugenya' refers specifically to the act of cutting the umbilical cord — one of the oldest surgical acts in human experience. Kinyarwanda captures it with a dedicated verb rather than borrowing from medical Latin.",
        "category": "Obstetrics",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Fever",
        "kinyarwanda": "Umuriro",
        "example_en": "The child has a high fever and should be taken to the clinic.",
        "example_rw": "Umwana afite umuriro ukomeye, agomba kujyanwa ku ivuriro.",
        "etymology": "'Umuriro' literally means 'fire' — the body burning with elevated temperature. This metaphor is shared across many languages.",
        "category": "General Medicine",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Tuberculosis",
        "kinyarwanda": "Igituntu",
        "example_en": "Tuberculosis treatment requires a complete course of antibiotics.",
        "example_rw": "Kuvura igituntu bisaba gufata imiti yose nk'uko byateganyijwe.",
        "etymology": "The established Kinyarwanda term, universally recognized across clinical settings in Rwanda.",
        "category": "Infectious Disease",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    {
        "english": "Diarrhea",
        "kinyarwanda": "Impiswi",
        "example_en": "Diarrhea in children can lead to severe dehydration.",
        "example_rw": "Impiswi mu bana zishobora gutera kubura amazi mu mubiri bikabije.",
        "etymology": "The standard Kinyarwanda term used across community health and clinical settings.",
        "category": "Gastroenterology",
        "contributed_by": "Christophe Mumaragishyika",
        "source": "Original starter terms"
    },
    # =================================================================
    # ANNIE CHIBWE CONSENT FORM (43 terms)
    # =================================================================
    {"english": "Anxiety", "kinyarwanda": "Ihangayika rikabije", "example_en": "The study measured anxiety levels among NCD patients.", "example_rw": "Ubushakashatsi bwapimye urwego rw'ihangayika rikabije mu barwayi b'indwara zitandura.", "etymology": "'Ihangayika' means worry or agitation. Adding 'rikabije' (severe) elevates it from everyday worry to the clinical concept of anxiety disorder.", "category": "Mental Health", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Depression", "kinyarwanda": "Agahinda gakabije", "example_en": "Depression can significantly affect treatment adherence.", "example_rw": "Agahinda gakabije gashobora kugira ingaruka ku myitwarire nyubahirizamiti ikwiye.", "etymology": "'Agahinda' uses the diminutive prefix aga- on the root -hinda (sadness), and 'gakabije' (severe/extreme) elevates it to a clinical condition.", "category": "Mental Health", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Asthma", "kinyarwanda": "Gusemeka / Isemeka", "example_en": "Asthma patients require regular follow-up at NCD clinics.", "example_rw": "Abarwayi barwaye gusemeka bakeneye gukurikiranwa buri gihe mu mavuriro y'indwara zitandura.", "etymology": "'Gusemeka' is the verbal form meaning 'to have difficulty breathing,' while 'isemeka' is the nominal form.", "category": "Pulmonology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Non-communicable disease", "kinyarwanda": "Indwara zitandura", "example_en": "Non-communicable diseases are a growing health concern in Rwanda.", "example_rw": "Indwara zitandura ni ikibazo cy'ubuzima kigenda gikura mu Rwanda.", "etymology": "'Indwara' means diseases, 'zitandura' uses the negative prefix zi- on -tandura (to spread/transmit). Literally 'diseases that do not spread.'", "category": "Public Health", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Mental health", "kinyarwanda": "Ubuzima bwo mu mutwe", "example_en": "Integrating mental health services into primary care is essential.", "example_rw": "Kongera serivisi zita ku buzima bwo mu mutwe muri serivizi z'ubuvuzi rusange z'ibanze ni ngombwa.", "etymology": "'Ubuzima' means health, 'bwo mu mutwe' means 'of the head/mind.' The anatomical metaphor locates the concept physically.", "category": "Mental Health", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Psychosocial support", "kinyarwanda": "Ubufasha nturishamutima", "example_en": "Participants who experience distress will be referred for psychosocial support.", "example_rw": "Abagize uruhare bahuye n'ibibazo bazashyirwa ku bufasha nturishamutima.", "etymology": "'Ubufasha' means help/assistance. 'Nturishamutima' is a compound: nturisha (to console/comfort) + umutima (heart). Literally 'help that consoles the heart.'", "category": "Mental Health", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Emotional distress", "kinyarwanda": "Ibyiyumviro nyegerezwamutima", "example_en": "Given the sensitive nature of mental health, participants may experience emotional distress.", "example_rw": "Hashingiwe k'uko guhangayika bikabije n'agahinda gakabije ari ibyiyumviro nyegerezwamutima.", "etymology": "'Ibyiyumviro' means feelings/emotions. 'Nyegerezwamutima' is a poetic compound: nyegerezo (pressing close) + umutima (heart).", "category": "Mental Health", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Treatment adherence", "kinyarwanda": "Myitwarire nyubahirizamiti ikwiye", "example_en": "Depression negatively impacts treatment adherence among NCD patients.", "example_rw": "Agahinda gakabije bigira ingaruka ku myitwarire nyubahirizamiti ikwiye mu barwayi b'indwara zitandura.", "etymology": "'Myitwarire' means behavior/conduct. 'Nyubahirizamiti' compounds nyubahiriza (to properly respect/follow) + imiti (medication).", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Primary care", "kinyarwanda": "Serivizi z'ubuvuzi rusange z'ibanze", "example_en": "Mental health services should be integrated into primary care.", "example_rw": "Serivisi zita ku buzima bwo mu mutwe zigomba kongerwa muri serivizi z'ubuvuzi rusange z'ibanze.", "etymology": "'Serivizi' is borrowed from French 'services.' 'Ubuvuzi rusange' means general medical care. 'Z'ibanze' means 'of the first/basic level.'", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Health center", "kinyarwanda": "Ikigo nderabuzima", "example_en": "The study was conducted at health centers in three districts.", "example_rw": "Ubushakashatsi bwakorerwe mu bigo nderabuzima byo mu turere dutatu.", "etymology": "'Ikigo' means center/institution. 'Nderabuzima' is a compound: ndera (to oversee/look after) + ubuzima (health).", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Physical injury", "kinyarwanda": "Gukomereka ku mubiri", "example_en": "If physical injury occurs as a result of participation, medical treatment will be available.", "example_rw": "Mu gihe habayeho gukomereka ku mubiri nk'ingaruka yo kugira uruhare, ubuvuzi burahari.", "etymology": "'Gukomereka' means to be hurt/injured. 'Ku mubiri' means 'on the body.'", "category": "General Medicine", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "First aid", "kinyarwanda": "Ubutabazi bw'ibanze", "example_en": "First aid will be provided in case of injury during the study.", "example_rw": "Ubutabazi bw'ibanze buzatangwa mu gihe habayeho gukomereka mu bushakashatsi.", "etymology": "'Ubutabazi' means help/rescue/assistance. 'Bw'ibanze' means 'of the first/basic kind.'", "category": "Emergency Medicine", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Emergency treatment", "kinyarwanda": "Ubutabizi ndengerabuzima bwihuse", "example_en": "Emergency treatment and follow-up care will be provided as needed.", "example_rw": "Ubutabizi ndengerabuzima bwihuse no gukurikiranwa uko bikwiriye bizatangwa.", "etymology": "'Ubutabizi' means treatment/care. 'Ndengerabuzima' compounds ndengera (emergency/crisis) + ubuzima (health). 'Bwihuse' means urgent/rapid.", "category": "Emergency Medicine", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Follow-up care", "kinyarwanda": "Gukurikiranwa uko bikwiriye", "example_en": "Patients with chronic conditions require regular follow-up care.", "example_rw": "Abarwayi b'indwara zidakira bakeneye gukurikiranwa uko bikwiriye buri gihe.", "etymology": "'Gukurikiranwa' is the passive form of gukurikirana (to follow up/monitor). 'Uko bikwiriye' means 'as is proper/appropriate.'", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Healthcare professional", "kinyarwanda": "Inzobere zikurikirana ubuzima", "example_en": "Participants may consult with healthcare professionals before deciding to participate.", "example_rw": "Abagize uruhare bashobora kugisha inama inzobere zikurikirana ubuzima mbere yo gufata umwanzuro.", "etymology": "'Inzobere' means expert/specialist. 'Zikurikirana ubuzima' means 'who follow/monitor health.'", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Insurance carrier", "kinyarwanda": "Ubwishingizi bw'ubuzima", "example_en": "Your insurance carrier may be billed for the cost of treatment.", "example_rw": "Ubwishingizi bw'ubuzima bwawe bushobora kwishyura ikiguzi cy'ubuvuzi.", "etymology": "'Ubwishingizi' means protection/guarantee/insurance. 'Bw'ubuzima' means 'of health.'", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Patient", "kinyarwanda": "Umurwayi", "example_en": "The patient should be informed of all risks before consenting.", "example_rw": "Umurwayi agomba kumenyeshwa ingorane zose mbere yo kwemera.", "etymology": "From 'kurwara' meaning 'to be ill/sick.' 'Umurwayi' is an agent noun — 'one who is ill.'", "category": "General Medicine", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Cross-sectional study", "kinyarwanda": "Inyigo mfatashushorusange ngambiriragihe", "example_en": "This is a cross-sectional study measuring prevalence at one point in time.", "example_rw": "Ubu bushakashatsi ni inyigo mfatashushorusange ngambiriragihe igamije kumenya ubwiganze.", "etymology": "A double neologism. 'Mfatashushorusange' = mfata (capture) + ishusho (picture) + rusange (general). 'Ngambiriragihe' = at one point in time.", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Prevalence", "kinyarwanda": "Ubwiganze", "example_en": "The study aims to determine the prevalence of depression among NCD patients.", "example_rw": "Ubushakashatsi bugamije kumenya ubwiganze bw'agahinda gakabije mu barwayi b'indwara zitandura.", "etymology": "From 'kwiganza' meaning 'to spread/be widespread.' 'Ubwiganze' is an abstract noun formed by the ubu- prefix.", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Risk factor", "kinyarwanda": "Impamvu nyongerabukana", "example_en": "Poverty is a significant risk factor for mental health disorders.", "example_rw": "Ubukene ni impamvu nyongerabukana ikomeye y'indwara zo mu mutwe.", "etymology": "'Impamvu' means reason/cause. 'Nyongerabukana' compounds nyongera (to increase) + ubukana (probability).", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Study population", "kinyarwanda": "Itsinda nkorerwahobushakashatsi", "example_en": "The study population includes patients aged 18 and above.", "example_rw": "Itsinda nkorerwahobushakashatsi rigizwe n'abarwayi bafite byibuze imyaka 18.", "etymology": "'Itsinda' means group. 'Nkorerwahobushakashatsi' = nkorerwa (for whom it is done) + ho (there) + ubushakashatsi (research).", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Participant", "kinyarwanda": "Umutangamakuru", "example_en": "Each participant will be assigned a unique identification number.", "example_rw": "Buri mutangamakuru azahabwa nimero imuranga yihariye.", "etymology": "'Umutangamakuru' = u-mu-tanga (one who gives) + amakuru (information). 'One who gives information.'", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Principal Investigator", "kinyarwanda": "Uhagarariye ubushakashatsi", "example_en": "The principal investigator oversees all aspects of the research project.", "example_rw": "Uhagarariye ubushakashatsi ni we ushinzwe impande zose z'ubushakashatsi.", "etymology": "'Uhagarariye' means 'the one who represents/leads.' Kinyarwanda expresses titles through function.", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Data collector", "kinyarwanda": "Umukusanyamakuru", "example_en": "The data collector will read each question to the participant.", "example_rw": "Umukusanyamakuru azasomera ibibazo buri mutangamakuru.", "etymology": "'Umukusanyamakuru' = u-mu-kusanya (one who gathers) + amakuru (information/data).", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Supervisor", "kinyarwanda": "Umugenzuzi", "example_en": "The research supervisor reviewed all collected data.", "example_rw": "Umugenzuzi w'ubushakashatsi yasuzumye amakuru yose yakusanyijwe.", "etymology": "From 'kugenzura' meaning 'to inspect/oversee/supervise.' A well-established agent noun.", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Questionnaire", "kinyarwanda": "Ifishi y'ibibazo nkusanyamakuru", "example_en": "The questionnaire contains closed-ended questions about mental health.", "example_rw": "Ifishi y'ibibazo nkusanyamakuru irimo ibibazo ntangamahitamo y'ibisubizo.", "etymology": "'Ifishi' borrowed from French 'fiche' (form/sheet). 'Nkusanyamakuru' = for gathering information.", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Closed-ended question", "kinyarwanda": "Ikibazo ntangamahitamo y'ibisubizo", "example_en": "All questions in the survey are closed-ended.", "example_rw": "Ibibazo byose biri mu bwoko bw'ibibazo ntangamahitamo y'ibisubizo.", "etymology": "'Ntangamahitamo y'ibisubizo' = 'that gives choices of answers.' A functional translation.", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Ethical approval", "kinyarwanda": "Uburenganzira nyemezabushakashatsi", "example_en": "The project received ethical approval from the UGHE IRB.", "example_rw": "Ubushakashatsi bwahawe uburenganzira nyemezabushakashatsi na UGHE.", "etymology": "'Uburenganzira' = rights/authorization. 'Nyemezabushakashatsi' = nyemeza (approve) + ubushakashatsi (research).", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Institutional Review Board (IRB)", "kinyarwanda": "Itsinda ngenzurabushakashatsi", "example_en": "The IRB reviewed and approved the research protocol.", "example_rw": "Itsinda ngenzurabushakashatsi ryasuzumye kandi ryemeza ubushakashatsi.", "etymology": "'Itsinda' = group/committee. 'Ngenzurabushakashatsi' = ngenzura (oversee/review) + ubushakashatsi (research).", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Informed consent", "kinyarwanda": "Itangaburenganzira ku itangamakuru mu bushakashatsi", "example_en": "Informed consent must be obtained before any research procedures begin.", "example_rw": "Itangaburenganzira ku itangamakuru mu bushakashatsi rigomba kubanza guhabwa.", "etymology": "'Itangaburenganzira' = itanga (giving) + uburenganzira (rights). Captures the dual nature of informed consent.", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Consent form", "kinyarwanda": "Inyandikomvugo ntangaburenganzira", "example_en": "Please read the consent form carefully before signing.", "example_rw": "Nyabuneka soma inyandikomvugo ntangaburenganzira witonze mbere yo gushyiraho umukono.", "etymology": "'Inyandikomvugo' = inyandiko (writing) + mvugo (speech/statement). 'Ntangaburenganzira' = that gives rights.", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Voluntary participation", "kinyarwanda": "Kwitabira ku bushake busesuye", "example_en": "Participation in this study is entirely voluntary.", "example_rw": "Kwitabira ubu bushakashatsi ni ku bushake busesuye.", "etymology": "'Kwitabira' = to participate. 'Ku bushake' = by willingness. 'Busesuye' = complete/full.", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Witness", "kinyarwanda": "Umutangabuhamya", "example_en": "A witness must sign the consent form alongside the participant.", "example_rw": "Umutangabuhamya agomba gushyira umukono ku nyandikomvugo ntangaburenganzira.", "etymology": "'Umutangabuhamya' = u-mu-tanga (one who gives) + ubuhamya (testimony).", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Signature", "kinyarwanda": "Umukono", "example_en": "Your signature indicates your consent to participate.", "example_rw": "Umukono wawe urerekana ko wemeye kugira uruhare.", "etymology": "'Umukono' literally means 'hand.' This metonymy — where the hand stands for the mark it makes — is ancient in Kinyarwanda.", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Confidentiality", "kinyarwanda": "Ibanga", "example_en": "All participant data will be kept confidential.", "example_rw": "Amakuru yose y'abagize uruhare azagumizwa mu ibanga.", "etymology": "'Ibanga' means secret or confidential matter. It carries deep cultural weight — ibanga implies a sacred trust.", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Password", "kinyarwanda": "Ijambobanga", "example_en": "Data will be stored on a password-protected computer.", "example_rw": "Amakuru azabikwa muri mudasobwa irinzwe n'ijambobanga.", "etymology": "'Ijambobanga' = ijambo (word) + ibanga (secret). 'Word of secrecy.'", "category": "Technology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Computer", "kinyarwanda": "Mudasobwa", "example_en": "The collected data will be stored in a password-protected computer.", "example_rw": "Amakuru yakusanyijwe azabikwa muri mudasobwa irinzwe n'ijambobanga.", "etymology": "'Mudasobwa' = mu-da-sobwa — 'that which does not make errors.' Negative prefix da- on sobwa (to err).", "category": "Technology", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Compensation", "kinyarwanda": "Impozamarira / Inshumbuho / Igihembo", "example_en": "Participants will not receive compensation for taking part in this study.", "example_rw": "Nta gihembo giteganijwe mu kugira uruhare muri ubu bushakashatsi.", "etymology": "Three types: 'impozamarira' (legal/financial), 'inshumbuho' (restitution), 'igihembo' (reward/payment). Context determines the choice.", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "To withdraw from a study", "kinyarwanda": "Guhagarika uruhare", "example_en": "You may withdraw from the study at any time without penalty.", "example_rw": "Ushobora guhagarika uruhare rwawe igihe icyo ari cyo cyose nta nkurikizi.", "etymology": "'Guhagarika' = to stop/cease. 'Uruhare' = role/part. Active voice emphasizes participant agency.", "category": "Research Ethics", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Copy (of document)", "kinyarwanda": "Impanga-shusho", "example_en": "You will receive a signed copy of this consent form.", "example_rw": "Uraza gushyikirizwa impanga-shusho iriho itariki n'umukono by'iyi fishi.", "etymology": "'Impanga-shusho' = impanga (replica/duplicate) + ishusho (image/likeness). 'Image replica.'", "category": "Administrative", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Ministry of Health", "kinyarwanda": "Minisiteri y'ubuzima", "example_en": "The results will inform decision-making within the Ministry of Health.", "example_rw": "Ibizava muri ubu bushakashatsi bizafasha mu ifatwa ry'ibyemezo muri Minisiteri y'ubuzima.", "etymology": "'Minisiteri' borrowed from French 'ministere.' 'Y'ubuzima' = of health.", "category": "Institutional", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "Partners in Health / Inshuti Mu Buzima (PIH/IMB)", "kinyarwanda": "Inshuti Mu Buzima (IMB)", "example_en": "This study is being carried out in collaboration with Partners in Health.", "example_rw": "Ubu bushakashatsi buri gukorwa ku bufatanye n'umuryango w'Inshuti Mu Buzima.", "etymology": "'Inshuti' = friends/partners. 'Mu Buzima' = in health. A semantic translation of the organization name.", "category": "Institutional", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    {"english": "University of Global Health Equity (UGHE)", "kinyarwanda": "Kaminuza iharanira uburinganire mu isigasirabuzima ku isi", "example_en": "The study was conducted under the auspices of UGHE.", "example_rw": "Ubushakashatsi bwakorerwe mu rwego rwa kaminuza iharanira uburinganire mu isigasirabuzima ku isi.", "etymology": "'Kaminuza' (university, from French). 'Iharanira' = that strives for. 'Uburinganire' = equality/equity. Every word is translated semantically.", "category": "Institutional", "contributed_by": "Christophe Mumaragishyika", "source": "Annie Chibwe consent form"},
    # =================================================================
    # DIABETES TYPE II IDI TRANSCRIPTS — June 2020 (20 terms)
    # =================================================================
    {"english": "Blood glucose level", "kinyarwanda": "Isukari mu maraso", "example_en": "My blood sugar tends to increase.", "example_rw": "Isukari yanjye ishaka kuzamuka.", "etymology": "'Isukari' = sugar. 'Mu maraso' = in the blood. Transparent compound used universally by patients — never the clinical term 'glycemia.'", "category": "Endocrinology", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Low blood glucose (Hypoglycemia)", "kinyarwanda": "Isukari nke mu maraso", "example_en": "In addressing the problem of having low blood glucose level...", "example_rw": "Mu gukurikirana ingorane zo kugira isukari nke mu maraso...", "etymology": "'Nke' = little/insufficient. Adding 'nke' to the base term creates the hypoglycemia concept through simple adjectival modification — no borrowing needed.", "category": "Endocrinology", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "High blood glucose (Hyperglycemia)", "kinyarwanda": "Isukari nyinshi mu maraso", "example_en": "My blood sugar increased too much, I am no longer able to do anything for myself.", "example_rw": "Isukari yambanyemo nyinshi cyane, ntakintu nkibasha kwikorera.", "etymology": "'Nyinshi' = much/many/high. The opposite of 'nke.' Patients describe severity through intensifiers: 'nyinshi' (high), 'nyinshi cyane' (very high).", "category": "Endocrinology", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Blood sugar measurement", "kinyarwanda": "Igipimo cy'isukari", "example_en": "I, too, will reach the readings below two hundred.", "example_rw": "Nanjye nzabone ibipimo biri munsi ya magana abiri.", "etymology": "'Igipimo' = measurement/level/reading (from 'gupima' = to measure). 'Cy'isukari' = of sugar.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "To test blood sugar", "kinyarwanda": "Gupima isukari mu maraso", "example_en": "Have you ever tried to measure your blood sugar at home?", "example_rw": "Utajya ugerageza gupima murugo igipimo cy'isukari?", "etymology": "'Gupima' = to measure/test. Used for both self-monitoring at home and clinical testing at health facilities.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "To fight/combat a disease", "kinyarwanda": "Guhashya indwara", "example_en": "What are the challenges you face in implementing strategies to fight diabetes type II?", "example_rw": "Imbogamizi uhura nazo mu gushyira mu bikorwa ingamba zo guhashya indwara ya gisukari yo mu bwoko bwa kabiri nizihe?", "etymology": "'Guhashya' = to fight against / to combat. A strong verb conveying active resistance against disease.", "category": "Public Health", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Disease prevention", "kinyarwanda": "Kwirinda indwara", "example_en": "That prevention is necessary because you never know from which source it may come.", "example_rw": "Ubwo bwirinzi nabwo burakenewe kuko ntuba uzi aho izaturuka.", "etymology": "'Kwirinda' = to protect oneself / to prevent. Reflexive verb — the -i- infix signals self-directed action.", "category": "Public Health", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "To monitor a disease", "kinyarwanda": "Kugenzura indwara", "example_en": "Which adequate means should be used in monitoring diabetes?", "example_rw": "Ni ubuhe buryo buboneye bwifashishwa mu kugenzura indwara ya gisukari?", "etymology": "'Kugenzura' = to inspect / oversee / monitor. Extends the supervisory concept into the disease monitoring context.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Sugary foods", "kinyarwanda": "Ibiryo by'ibinyamasukari", "example_en": "One has to abstain from excess sugary foods, for instance: cookies, juices.", "example_rw": "Umuntu agomba kwirinda ibiryo by'ibinyamasukari byinshi, urugero: ama biscuits, ama jus.", "etymology": "'Ibiryo' = foods. 'By'ibinyamasukari' = of sugary things. 'Ibinyamasukari' compounds ibintu (things) + ama (of) + sukari (sugar).", "category": "Nutrition", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Medication", "kinyarwanda": "Imiti", "example_en": "I need medications that require much money.", "example_rw": "Nkeneye imiti isaba amafaranga menshi.", "etymology": "Plural of 'umuti' (medicine/drug). Universal term across all clinical contexts in Kinyarwanda.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Herbal remedies / Traditional medicine", "kinyarwanda": "Imiti ikomoka ku bimera / Ubuvuzi bukoresha imiti gakondo", "example_en": "Other patients told me they now use herbal remedies.", "example_rw": "Abandi bayirwaye bakambwira bati dusigaye dukoresha imiti ikomoka ku bimera.", "etymology": "'Imiti ikomoka ku bimera' = medicine that comes from plants. 'Ubuvuzi bukoresha imiti gakondo' = treatment using traditional medicine. 'Gakondo' = traditional, reflecting that traditional medication was based on herbal remedies.", "category": "Traditional Medicine", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Health behavior / Lifestyle conduct", "kinyarwanda": "Imyifatire", "example_en": "They tell me how I should behave and how I should eat.", "example_rw": "Bambwire uko ngomba kwitwara nuko ngomba kurya.", "etymology": "From 'kwifata' = to conduct oneself. 'Imyifatire' = manner of self-conduct. In diabetes context, encompasses diet, medication adherence, exercise, and all behavioral management.", "category": "Public Health", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Clinical instructions / Doctor's recommendations", "kinyarwanda": "Amabwiriza yo kwa muganga", "example_en": "Provide me with the doctor's instructions on how I should behave and the medication I should take.", "example_rw": "Bampe amabwiriza yo kwa muganga yuko ngomba kwitwara, n'imiti ngomba gufata.", "etymology": "'Amabwiriza' = instructions (from 'kubwiriza' = to instruct). 'Yo kwa muganga' = from the doctor. Specifies the clinical source of authority.", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Barriers to care", "kinyarwanda": "Imbogamizi zibangamira kwitabwaho / Imbogamizi zibuza kuvurwa", "example_en": "What are the challenges you face in implementing strategies prescribed by the doctor?", "example_rw": "Imbogamizi zibangamira kwitabwaho uhura nazo mu gushyira mu bikorwa ingamba wahawe na muganga nizihe?", "etymology": "'Imbogamizi' = obstacles (from 'kubogamiza' = to obstruct). 'Zibangamira kwitabwaho' = that hinder being cared for. 'Zibuza kuvurwa' = that prevent being treated.", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Poverty (as a barrier to healthcare)", "kinyarwanda": "Ubukene (nk'imbogamizi)", "example_en": "The prevailing obstacle is actually that poverty.", "example_rw": "Imbogamizi iba ihari ni ubwo bukene nyine.", "etymology": "From 'gukena' = to be poor/lacking. 'Ubukene' = poverty/destitution. 'Nk'imbogamizi' = as an obstacle. Repeatedly cited by patients as the primary barrier to diabetes management.", "category": "Social Determinants", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Health advice / Medical counseling", "kinyarwanda": "Inama z'ubuzima", "example_en": "Especially in advice... and also about medical care.", "example_rw": "Cyane cyane ku nama... nibijyanye no kwivuza.", "etymology": "'Inama' = advice/counsel. 'Z'ubuzima' = of health. Patients overwhelmingly identify the need for health advice as their primary unmet need.", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Healthcare assistance / Medical support", "kinyarwanda": "Ubwunganizi bwita ku buzima / Ubwunganizi mu kuvurwa", "example_en": "In which side do you need further assistance?", "example_rw": "Ni mu ruhe ruhande ukeneye ubwunganizi bwita ku buzima bwisumbuye ho?", "etymology": "'Ubwunganizi' = support/assistance (from 'kunganira' = to support). 'Bwita ku buzima' = that cares for health. 'Mu kuvurwa' = in being treated.", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Information dissemination / Health sensitization", "kinyarwanda": "Gusakaza amakuru", "example_en": "Which adequate means should be used to disseminate needed information?", "example_rw": "Ni ubuhe buryo buboneye bwifashishwa mu gusakaza amakuru akenewe?", "etymology": "'Gusakaza' = to scatter/spread/disseminate. 'Amakuru' = information/news. A precise verb for health communication campaigns.", "category": "Public Health", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "To seek medical treatment", "kinyarwanda": "Kwivuza", "example_en": "And also about seeking medical treatment.", "example_rw": "Nibijyanye no kwivuza urebye.", "etymology": "Reflexive of 'kuvuza' (to treat/heal). 'Kwivuza' = to seek treatment for oneself. The reflexive marks patient agency.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    {"english": "Health follow-up / Medical monitoring", "kinyarwanda": "Gukurikirana ubuzima", "example_en": "Maybe I would have a health follow-up and then tell me where to get medications.", "example_rw": "Wenda mwajya munkurikirana mukareba ko mwandangira cyangwa mwampa imiti ngomba gukoresha.", "etymology": "'Gukurikirana' = to follow up / to track / to monitor. 'Ubuzima' = health. Describes the active, ongoing process of medical monitoring.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Diabetes Type II IDI transcripts (2020)"},
    # =================================================================
    # SP/PEDS LETTER + SEARCH LOG + COMMUNITY SUGGESTIONS (27 terms)
    # Added April 2026 from Term Tracker Review 1
    # =================================================================
    # --- Tier 1: High-priority terms from search logs & community ---
    {"english": "Doctor / Physician", "kinyarwanda": "Umuganga", "example_en": "The doctor examined the patient carefully.", "example_rw": "Umuganga yasuzumye umurwayi yitonze.", "etymology": "Established Kinyarwanda term used universally across all clinical contexts in Rwanda.", "category": "General Medicine", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Headache", "kinyarwanda": "Kuribwa n'umutwe / Kuribwa umutwe / Kubabara umutwe", "example_en": None, "example_rw": None, "etymology": None, "category": "Neurology / Symptoms", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Liver", "kinyarwanda": "Umwijima", "example_en": None, "example_rw": None, "etymology": None, "category": "Anatomy", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Pneumonia", "kinyarwanda": "Umusonga", "example_en": None, "example_rw": None, "etymology": None, "category": "Pulmonology", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Brain", "kinyarwanda": "Ubwonko", "example_en": None, "example_rw": None, "etymology": None, "category": "Anatomy", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Brain cancer", "kinyarwanda": "Kimungu y'ubwonko", "example_en": None, "example_rw": None, "etymology": "'Kimungu' = cancer, from the verb 'kumunga' (to eat up) — what tumors do to the living cells of the organ they attack. 'Y'ubwonko' = of the brain.", "category": "Oncology / Neurology", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Gall bladder", "kinyarwanda": "Agasabo k'indurwe", "example_en": None, "example_rw": None, "etymology": "'Indurwe' means bile. 'Agasabo' means a small bag — which is the apparent role of the gall bladder: to store bile.", "category": "Anatomy", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Pancreas", "kinyarwanda": "Urwagashya", "example_en": None, "example_rw": None, "etymology": None, "category": "Anatomy", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Contraception", "kinyarwanda": "Kuringaniza urubyaro", "example_en": None, "example_rw": None, "etymology": "'Kuringaniza urubyaro' = birth control. 'Kuringaniza' = to balance/regulate. 'Urubyaro' = childbearing/reproduction.", "category": "Reproductive Health", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Swelling", "kinyarwanda": "Kubyimba / Kubyimbagatana", "example_en": None, "example_rw": None, "etymology": None, "category": "Symptoms", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Silicosis", "kinyarwanda": "Kanigabihaha", "example_en": None, "example_rw": None, "etymology": "'Kaniga' from 'kuniga' (to stifle). 'Ibihaha' = lungs. Literally: makes your lungs stiff, making it harder and harder to breathe.", "category": "Pulmonology / Occupational Health", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Palliative care", "kinyarwanda": "Ubuvuzi mpozaburibwe / Ubufasha nyunganiramibereho", "example_en": None, "example_rw": None, "etymology": "'Mpoza' from 'guhoza/guturisha' (to comfort). 'Buribwe' from 'uburibwe' (pain). Palliative care is a medical specialty focused on comfort while treating serious illness — fixing physical discomfort, easing the mind. 'Nyunganiramibereho' = supporting quality of life.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "Community suggestion — Mugenzi (UGHE)"},
    {"english": "Interview (research methodology)", "kinyarwanda": "Ikiganiro mbona-nkubone", "example_en": None, "example_rw": None, "etymology": "Interviewing involves asking questions face to face and exchanging speech. 'Kuganira' = holding a talk. 'Mbona-nkubone' = live, face to face.", "category": "Research Methodology", "contributed_by": "Christophe Mumaragishyika", "source": "Community suggestion — Benithe Himbazwa (UGHE student)"},
    {"english": "Health management", "kinyarwanda": "Igenamigambi ncungamikorere mu buvuzi", "example_en": None, "example_rw": None, "etymology": "'Igenamigambi' from 'kugena imigambi' = planning. 'Ncungamikorere' = leading operations. Health management involves leading, planning, and coordinating medical services, focusing on operational efficiency, staff management, and patient outcomes.", "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Community suggestion — Benithe Himbazwa (UGHE student)"},
    # --- Tier 2: SP/PEDS letter terms (pre-translated by Khris) ---
    {"english": "Standardized Patient", "kinyarwanda": "Umurwayi mfashamibarize", "example_en": "The medical school recruits children to serve as standardized patients during examinations.", "example_rw": "Kaminuza y'ubuvuzi ihamagara abana kugira ngo bagire uruhare mu isuzumabumenyi ry'abanyeshuri nk'abarwayi mfashamibarize.", "etymology": "Neologism compound: 'mfasha' (help) + 'mibarize' (assessment/examination). Captures the role of helping with clinical assessment by acting as a patient.", "category": "Medical Education", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Medical training program", "kinyarwanda": "Gahunda y'uburezi nderabaganga n'abavuzi", "example_en": "This educational activity is a valuable component of our medical training program.", "example_rw": "Uyu mukoro ni ingenzi mu bigize gahunda y'uburezi nderabaganga n'abavuzi.", "etymology": "'Gahunda' = program. 'Uburezi' = education. 'Nderabaganga' compounds 'ndera' (oversee) + 'abaganga' (doctors). Same -ndera- pattern as 'ikigo nderabuzima' (health center).", "category": "Medical Education", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Clinical and communication skills", "kinyarwanda": "Ubushobozi bwo kumvikana n'abarwayi binyuze mu kubumva no kubatega amatwi", "example_en": "Future doctors develop essential clinical and communication skills in supervised settings.", "example_rw": "Abaganga b'ejo hazaza bagaragaza ubushobozi bwo kumvikana n'abarwayi binyuze mu kubumva no kubatega amatwi mu mikorere yagenzuwe.", "etymology": "Literally: 'ability to communicate with patients through understanding and listening to them.' Functional, descriptive translation that captures both clinical and communication dimensions.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Assessment (clinical)", "kinyarwanda": "Amabazwa nsuzumabumenyi bwa kiganga", "example_en": "Children play an important role in these clinical assessments.", "example_rw": "Abana bagira umumaro w'ingenzi muri aya mabazwa.", "etymology": "From 'kubaza' (to question/examine). 'Amabazwa' = the things asked or examined. Existing Kinyarwanda term repurposed for clinical context. 'Kiganga' implies the clinical scope.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Patient-centered care", "kinyarwanda": "Imivurire ishingiye ku mikoranire y'umuganga n'umurwayi", "example_en": "Standardized patient sessions help train students in patient-centered care.", "example_rw": "Imikoro y'umurwayi mfashamibarize ifasha gutoza abanyeshuri gukoresha imivurire ishingiye ku mikoranire y'abaganga n'abarwayi.", "etymology": "'Imivurire' = care/treatment approach. 'Ishingiye ku mikoranire' = based on the interaction/collaboration. 'Y'umuganga n'umurwayi' = between doctor and patient. Captures the collaborative, patient-centered dimension.", "category": "Clinical Practice", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Well-being (child's)", "kinyarwanda": "Ubuzima bwite bw'umwana", "example_en": "This opportunity will be respectful of the child's well-being.", "example_rw": "Uyu mukoro uba wubahiriza ubuzima bwite bw'umwana.", "etymology": "'Ubuzima' = health/life. 'Bwite' = personal/private/own. 'Bw'umwana' = of the child. Together: the personal health of the child.", "category": "Pediatrics / General", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Holistic development", "kinyarwanda": "Kurera", "example_en": "We value your school's role in the holistic development of your students.", "example_rw": "Duha agaciro kenshi uruhare mugira mu kurera abanyeshuri b'ikigo muyobora.", "etymology": "'Kurera' = to raise/nurture. The verb encompasses the full range of physical, intellectual, and moral development — making it a natural fit for 'holistic development' in educational contexts.", "category": "Education / Pediatrics", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    # --- Tier 3: Administrative/contextual terms ---
    {"english": "To Whom It May Concern", "kinyarwanda": "Ku bo bireba", "example_en": "To Whom It May Concern, We kindly request your permission...", "example_rw": "Ku bo bireba, Tubandikiye tubasaba uburenganzira...", "etymology": "'Ku bo' = to those. 'Bireba' = whom it concerns. Standard formal Kinyarwanda letter opening.", "category": "Administrative / Letter Writing", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Contact information", "kinyarwanda": "Amakuru y'uko bamugeraho", "example_en": "Please find my contact information below.", "example_rw": "Amakuru y'uko bamugeraho araboneka hano hasi.", "etymology": "'Amakuru' = information. 'Y'uko bamugeraho' = of how to reach them. Literally: 'information about how to reach them.'", "category": "Administrative", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    {"english": "Division / Department", "kinyarwanda": "Ishami nshingwabikorwa", "example_en": "I work in the Division of Clinical Medicine.", "example_rw": "Nkorera mu ishami nshingwabikorwa rishinzwe abakozi.", "etymology": "'Ishami' = branch/division. 'Nshingwabikorwa' = assigned operations/responsibilities. Established institutional term.", "category": "Institutional", "contributed_by": "Christophe Mumaragishyika", "source": "SP/PEDS letter (Khris translation, 2025)"},
    # --- Tier 5: Lower priority but with verified translations ---
    {"english": "How are you feeling today", "kinyarwanda": "Uyu munsi murumva mumerewe mute?", "example_en": None, "example_rw": None, "etymology": None, "category": "Clinical Phrases", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Surgery", "kinyarwanda": "Kubaga abarwayi", "example_en": "She wants to specialize in Surgery.", "example_rw": "Arifuza kuba inzobere mu byo kubaga abarwayi.", "etymology": None, "category": "Surgical", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
    {"english": "Medical appointment", "kinyarwanda": "Gahunda yo kubonana na muganga", "example_en": None, "example_rw": None, "etymology": None, "category": "Health Systems", "contributed_by": "Christophe Mumaragishyika", "source": "Search log demand (Apr 2026)"},
]


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # Create admin if not exists
        if not Admin.query.filter_by(username=ADMIN_USERNAME).first():
            admin = Admin(username=ADMIN_USERNAME)
            admin.set_password(ADMIN_PASSWORD)
            print(f"✓ Admin user '{ADMIN_USERNAME}' created")
        else:
            print(f"→ Admin user '{ADMIN_USERNAME}' already exists")

        # Add terms (skip duplicates by English name)
        added = 0
        skipped = 0
        for term_data in STARTER_TERMS:
            existing = Term.query.filter_by(english=term_data["english"]).first()
            if not existing:
                db.session.add(Term(**term_data))
                added += 1
            else:
                skipped += 1

        db.session.commit()
        total = Term.query.count()
        print(f"✓ Added {added} new terms ({skipped} already existed)")
        print(f"\n  Total terms in dictionary: {total}")


if __name__ == "__main__":
    seed()