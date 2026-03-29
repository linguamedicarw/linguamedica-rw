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

# ------ CONFIGURATION ------
# Change these before running!
ADMIN_USERNAME = "khris"
ADMIN_PASSWORD = "***REMOVED***"  # CHANGE THIS to something strong!

# ------ ALL TERMS ------
STARTER_TERMS = [
    {
        "english": "Hypertension",
        "kinyarwanda": "Umuvuduko w'amaraso",
        "example_en": "The patient was diagnosed with hypertension.",
        "example_rw": "Umurwayi yasuzumwe afite umuvuduko w'amaraso.",
        "etymology": "'Umuvuduko' means pressure or force, 'w'amaraso' means of the blood — literally 'pressure of the blood.'",
        "category": "Cardiology"
    },
    {
        "english": "Diabetes",
        "kinyarwanda": "Diyabete / Indwara y'igisukari",
        "example_en": "Diabetes requires careful management of blood sugar levels.",
        "example_rw": "Diyabete isaba kwitaho neza urwego rw'isukari mu maraso.",
        "etymology": "'Indwara y'igisukari' literally translates to 'disease of sugar,' which accurately captures the core characteristic of diabetes — the body's inability to regulate blood sugar.",
        "category": "Endocrinology"
    },
    {
        "english": "Malaria",
        "kinyarwanda": "Malariya",
        "example_en": "Malaria is transmitted through mosquito bites.",
        "example_rw": "Malariya ikwirakwizwa n'umubu.",
        "etymology": "The term 'Malariya' is a direct phonetic adaptation from the international medical term. It is universally understood in Rwandan health contexts.",
        "category": "Infectious Disease"
    },
    {
        "english": "Vaccination",
        "kinyarwanda": "Ikingira",
        "example_en": "Vaccination is essential for preventing childhood diseases.",
        "example_rw": "Ikingira ni ngombwa mu gukinga indwara z'abana.",
        "etymology": "From 'gukingira' meaning 'to protect' — literally 'the protection.' The word captures the preventive essence of vaccination.",
        "category": "Public Health"
    },
    {
        "english": "Pregnancy",
        "kinyarwanda": "Gutwita / Inda",
        "example_en": "Regular check-ups during pregnancy are important.",
        "example_rw": "Gusuzumwa buri gihe mu gihe cy'inda ni ngombwa.",
        "etymology": "'Gutwita' is the verb 'to be pregnant,' while 'inda' refers to the pregnancy or the womb itself. Both are used interchangeably depending on context.",
        "category": "Maternal Health"
    },
    {
        "english": "Anemia",
        "kinyarwanda": "Kubura amaraso",
        "example_en": "Anemia can cause fatigue and weakness.",
        "example_rw": "Kubura amaraso bishobora gutera umunaniro n'intege nke.",
        "etymology": "'Kubura' means 'to lack,' 'amaraso' means 'blood' — literally 'lacking blood.' This descriptive translation immediately communicates the condition to patients.",
        "category": "Hematology"
    },
    {
        "english": "Omphalotomy",
        "kinyarwanda": "Kugenya",
        "example_en": "The midwife performed the omphalotomy immediately after delivery.",
        "example_rw": "Umubyaza yakoze kugenya ako kanya nyuma yo kubyara.",
        "etymology": "'Kugenya' refers specifically to the act of cutting the umbilical cord — one of the oldest surgical acts in human experience. Kinyarwanda captures it with a dedicated verb rather than borrowing from medical Latin.",
        "category": "Obstetrics"
    },
    {
        "english": "Fever",
        "kinyarwanda": "Umuriro",
        "example_en": "The child has a high fever and should be taken to the clinic.",
        "example_rw": "Umwana afite umuriro ukomeye, agomba kujyanwa ku ivuriro.",
        "etymology": "'Umuriro' literally means 'fire' — the body burning with elevated temperature. This metaphor is shared across many languages.",
        "category": "General Medicine"
    },
    {
        "english": "Tuberculosis",
        "kinyarwanda": "Igituntu",
        "example_en": "Tuberculosis treatment requires a complete course of antibiotics.",
        "example_rw": "Kuvura igituntu bisaba gufata imiti yose nk'uko byateganyijwe.",
        "etymology": "The established Kinyarwanda term, universally recognized across clinical settings in Rwanda.",
        "category": "Infectious Disease"
    },
    {
        "english": "Diarrhea",
        "kinyarwanda": "Impiswi",
        "example_en": "Diarrhea in children can lead to severe dehydration.",
        "example_rw": "Impiswi mu bana zishobora gutera kubura amazi mu mubiri bikabije.",
        "etymology": "The standard Kinyarwanda term used across community health and clinical settings.",
        "category": "Gastroenterology"
    },
    {
        "english": "Anxiety",
        "kinyarwanda": "Ihangayika rikabije",
        "example_en": "The study measured anxiety levels among NCD patients.",
        "example_rw": "Ubushakashatsi bwapimye urwego rw'ihangayika rikabije mu barwayi b'indwara zitandura.",
        "etymology": "'Ihangayika' means worry or agitation. Adding 'rikabije' (severe) elevates it from everyday worry to the clinical concept of anxiety disorder.",
        "category": "Mental Health"
    },
    {
        "english": "Depression",
        "kinyarwanda": "Agahinda gakabije",
        "example_en": "Depression can significantly affect treatment adherence.",
        "example_rw": "Agahinda gakabije gashobora kugira ingaruka ku myitwarire nyubahirizamiti ikwiye.",
        "etymology": "'Agahinda' uses the diminutive prefix aga- on the root -hinda (sadness), and 'gakabije' (severe/extreme) elevates it to a clinical condition. The diminutive prefix here conveys depth rather than smallness.",
        "category": "Mental Health"
    },
    {
        "english": "Asthma",
        "kinyarwanda": "Gusemeka / Isemeka",
        "example_en": "Asthma patients require regular follow-up at NCD clinics.",
        "example_rw": "Abarwayi barwaye gusemeka bakeneye gukurikiranwa buri gihe mu mavuriro y'indwara zitandura.",
        "etymology": "'Gusemeka' is the verbal form meaning 'to have difficulty breathing,' while 'isemeka' is the nominal form. Both derive from the lived experience of labored breathing.",
        "category": "Pulmonology"
    },
    {
        "english": "Non-communicable disease",
        "kinyarwanda": "Indwara zitandura",
        "example_en": "Non-communicable diseases are a growing health concern in Rwanda.",
        "example_rw": "Indwara zitandura ni ikibazo cy'ubuzima kigenda gikura mu Rwanda.",
        "etymology": "'Indwara' means diseases, 'zitandura' uses the negative prefix zi- on -tandura (to spread/transmit). Literally 'diseases that do not spread.'",
        "category": "Public Health"
    },
    {
        "english": "Mental health",
        "kinyarwanda": "Ubuzima bwo mu mutwe",
        "example_en": "Integrating mental health services into primary care is essential.",
        "example_rw": "Kongera serivisi zita ku buzima bwo mu mutwe muri serivizi z'ubuvuzi rusange z'ibanze ni ngombwa.",
        "etymology": "'Ubuzima' means health, 'bwo mu mutwe' means 'of the head/mind.' The anatomical metaphor locates the concept physically, making it accessible to patients.",
        "category": "Mental Health"
    },
    {
        "english": "Psychosocial support",
        "kinyarwanda": "Ubufasha nturishamutima",
        "example_en": "Participants who experience distress will be referred for psychosocial support.",
        "example_rw": "Abagize uruhare bahuye n'ibibazo bazashyirwa ku bufasha nturishamutima.",
        "etymology": "'Ubufasha' means help/assistance. 'Nturishamutima' is a compound: nturisha (to console/comfort) + umutima (heart). Literally 'help that consoles the heart.'",
        "category": "Mental Health"
    },
    {
        "english": "Emotional distress",
        "kinyarwanda": "Ibyiyumviro nyegerezwamutima",
        "example_en": "Given the sensitive nature of mental health, participants may experience emotional distress.",
        "example_rw": "Hashingiwe k'uko guhangayika bikabije n'agahinda gakabije ari ibyiyumviro nyegerezwamutima.",
        "etymology": "'Ibyiyumviro' means feelings/emotions. 'Nyegerezwamutima' is a poetic compound: nyegerezo (pressing close) + umutima (heart). Literally 'feelings that press close to the heart.'",
        "category": "Mental Health"
    },
    {
        "english": "Treatment adherence",
        "kinyarwanda": "Myitwarire nyubahirizamiti ikwiye",
        "example_en": "Depression negatively impacts treatment adherence among NCD patients.",
        "example_rw": "Agahinda gakabije bigira ingaruka ku myitwarire nyubahirizamiti ikwiye mu barwayi b'indwara zitandura.",
        "etymology": "'Myitwarire' means behavior/conduct. 'Nyubahirizamiti' compounds nyubahiriza (to properly respect/follow) + imiti (medication). The full phrase captures the behavioral dimension of adherence.",
        "category": "Clinical Practice"
    },
    {
        "english": "Primary care",
        "kinyarwanda": "Serivizi z'ubuvuzi rusange z'ibanze",
        "example_en": "Mental health services should be integrated into primary care.",
        "example_rw": "Serivisi zita ku buzima bwo mu mutwe zigomba kongerwa muri serivizi z'ubuvuzi rusange z'ibanze.",
        "etymology": "'Serivizi' is borrowed from French 'services.' 'Ubuvuzi rusange' means general medical care. 'Z'ibanze' means 'of the first/basic level.'",
        "category": "Health Systems"
    },
    {
        "english": "Health center",
        "kinyarwanda": "Ikigo nderabuzima",
        "example_en": "The study was conducted at health centers in three districts.",
        "example_rw": "Ubushakashatsi bwakorerwe mu bigo nderabuzima byo mu turere dutatu.",
        "etymology": "'Ikigo' means center/institution. 'Nderabuzima' is a compound: ndera (to oversee/look after) + ubuzima (health). Literally 'institution that oversees health.'",
        "category": "Health Systems"
    },
    {
        "english": "Physical injury",
        "kinyarwanda": "Gukomereka ku mubiri",
        "example_en": "If physical injury occurs as a result of participation, medical treatment will be available.",
        "example_rw": "Mu gihe habayeho gukomereka ku mubiri nk'ingaruka yo kugira uruhare, ubuvuzi burahari.",
        "etymology": "'Gukomereka' means to be hurt/injured. 'Ku mubiri' means 'on the body' — specifying physical as opposed to emotional harm.",
        "category": "General Medicine"
    },
    {
        "english": "First aid",
        "kinyarwanda": "Ubutabazi bw'ibanze",
        "example_en": "First aid will be provided in case of injury during the study.",
        "example_rw": "Ubutabazi bw'ibanze buzatangwa mu gihe habayeho gukomereka mu bushakashatsi.",
        "etymology": "'Ubutabazi' means help/rescue/assistance. 'Bw'ibanze' means 'of the first/basic kind.' The term conveys both urgency and priority.",
        "category": "Emergency Medicine"
    },
    {
        "english": "Emergency treatment",
        "kinyarwanda": "Ubutabizi ndengerabuzima bwihuse",
        "example_en": "Emergency treatment and follow-up care will be provided as needed.",
        "example_rw": "Ubutabizi ndengerabuzima bwihuse no gukurikiranwa uko bikwiriye bizatangwa.",
        "etymology": "'Ubutabizi' means treatment/care. 'Ndengerabuzima' compounds ndengera (emergency/crisis) + ubuzima (health). 'Bwihuse' means urgent/rapid.",
        "category": "Emergency Medicine"
    },
    {
        "english": "Follow-up care",
        "kinyarwanda": "Gukurikiranwa uko bikwiriye",
        "example_en": "Patients with chronic conditions require regular follow-up care.",
        "example_rw": "Abarwayi b'indwara zidakira bakeneye gukurikiranwa uko bikwiriye buri gihe.",
        "etymology": "'Gukurikiranwa' is the passive form of gukurikirana (to follow up/monitor). 'Uko bikwiriye' means 'as is proper/appropriate.'",
        "category": "Clinical Practice"
    },
    {
        "english": "Healthcare professional",
        "kinyarwanda": "Inzobere zikurikirana ubuzima",
        "example_en": "Participants may consult with healthcare professionals before deciding to participate.",
        "example_rw": "Abagize uruhare bashobora kugisha inama inzobere zikurikirana ubuzima mbere yo gufata umwanzuro.",
        "etymology": "'Inzobere' means expert/specialist. 'Zikurikirana ubuzima' means 'who follow/monitor health.'",
        "category": "Health Systems"
    },
    {
        "english": "Insurance carrier",
        "kinyarwanda": "Ubwishingizi bw'ubuzima",
        "example_en": "Your insurance carrier may be billed for the cost of treatment.",
        "example_rw": "Ubwishingizi bw'ubuzima bwawe bushobora kwishyura ikiguzi cy'ubuvuzi.",
        "etymology": "'Ubwishingizi' means protection/guarantee/insurance. 'Bw'ubuzima' means 'of health.' The term frames insurance as health protection.",
        "category": "Health Systems"
    },
    {
        "english": "Patient",
        "kinyarwanda": "Umurwayi",
        "example_en": "The patient should be informed of all risks before consenting.",
        "example_rw": "Umurwayi agomba kumenyeshwa ingorane zose mbere yo kwemera.",
        "etymology": "From 'kurwara' meaning 'to be ill/sick.' 'Umurwayi' is an agent noun — 'one who is ill.' One of the most fundamental medical terms in Kinyarwanda.",
        "category": "General Medicine"
    },
    {
        "english": "Cross-sectional study",
        "kinyarwanda": "Inyigo mfatashushorusange ngambiriragihe",
        "example_en": "This is a cross-sectional study measuring prevalence at one point in time.",
        "example_rw": "Ubu bushakashatsi ni inyigo mfatashushorusange ngambiriragihe igamije kumenya ubwiganze.",
        "etymology": "A double neologism. 'Mfatashushorusange' = mfata (capture) + ishusho (picture) + rusange (general). 'Ngambiriragihe' = at one point in time. Together they express both the snapshot nature and temporal dimension of cross-sectional research.",
        "category": "Research Methodology"
    },
    {
        "english": "Prevalence",
        "kinyarwanda": "Ubwiganze",
        "example_en": "The study aims to determine the prevalence of depression among NCD patients.",
        "example_rw": "Ubushakashatsi bugamije kumenya ubwiganze bw'agahinda gakabije mu barwayi b'indwara zitandura.",
        "etymology": "From 'kwiganza' meaning 'to spread/be widespread.' 'Ubwiganze' is an abstract noun formed by the ubu- prefix, capturing how widespread a condition is in a population.",
        "category": "Research Methodology"
    },
    {
        "english": "Risk factor",
        "kinyarwanda": "Impamvu nyongerabukana",
        "example_en": "Poverty is a significant risk factor for mental health disorders.",
        "example_rw": "Ubukene ni impamvu nyongerabukana ikomeye y'indwara zo mu mutwe.",
        "etymology": "'Impamvu' means reason/cause. 'Nyongerabukana' compounds nyongera (to increase) + ubukana (probability). Literally 'reasons that increase the probability.'",
        "category": "Research Methodology"
    },
    {
        "english": "Study population",
        "kinyarwanda": "Itsinda nkorerwahobushakashatsi",
        "example_en": "The study population includes patients aged 18 and above.",
        "example_rw": "Itsinda nkorerwahobushakashatsi rigizwe n'abarwayi bafite byibuze imyaka 18.",
        "etymology": "'Itsinda' means group. 'Nkorerwahobushakashatsi' = nkorerwa (for whom it is done) + ho (there) + ubushakashatsi (research). 'The group for whom research is done.'",
        "category": "Research Methodology"
    },
    {
        "english": "Participant",
        "kinyarwanda": "Umutangamakuru",
        "example_en": "Each participant will be assigned a unique identification number.",
        "example_rw": "Buri mutangamakuru azahabwa nimero imuranga yihariye.",
        "etymology": "'Umutangamakuru' = u-mu-tanga (one who gives) + amakuru (information). 'One who gives information.' This reframes the participant as an active contributor, not a passive subject.",
        "category": "Research Methodology"
    },
    {
        "english": "Principal Investigator",
        "kinyarwanda": "Uhagarariye ubushakashatsi",
        "example_en": "The principal investigator oversees all aspects of the research project.",
        "example_rw": "Uhagarariye ubushakashatsi ni we ushinzwe impande zose z'ubushakashatsi.",
        "etymology": "'Uhagarariye' means 'the one who represents/leads.' Kinyarwanda expresses titles through function using relative clause construction, not borrowed terminology.",
        "category": "Research Methodology"
    },
    {
        "english": "Data collector",
        "kinyarwanda": "Umukusanyamakuru",
        "example_en": "The data collector will read each question to the participant.",
        "example_rw": "Umukusanyamakuru azasomera ibibazo buri mutangamakuru.",
        "etymology": "'Umukusanyamakuru' = u-mu-kusanya (one who gathers) + amakuru (information/data). An agent noun that precisely describes the field role in research.",
        "category": "Research Methodology"
    },
    {
        "english": "Supervisor",
        "kinyarwanda": "Umugenzuzi",
        "example_en": "The research supervisor reviewed all collected data.",
        "example_rw": "Umugenzuzi w'ubushakashatsi yasuzumye amakuru yose yakusanyijwe.",
        "etymology": "From 'kugenzura' meaning 'to inspect/oversee/supervise.' A well-established agent noun used across professional contexts.",
        "category": "Research Methodology"
    },
    {
        "english": "Questionnaire",
        "kinyarwanda": "Ifishi y'ibibazo nkusanyamakuru",
        "example_en": "The questionnaire contains closed-ended questions about mental health.",
        "example_rw": "Ifishi y'ibibazo nkusanyamakuru irimo ibibazo ntangamahitamo y'ibisubizo.",
        "etymology": "'Ifishi' borrowed from French 'fiche' (form/sheet). 'Y'ibibazo' = of questions. 'Nkusanyamakuru' = for gathering information. This blend of French borrowing and Kinyarwanda compounds reflects dual colonial linguistic heritage.",
        "category": "Research Methodology"
    },
    {
        "english": "Closed-ended question",
        "kinyarwanda": "Ikibazo ntangamahitamo y'ibisubizo",
        "example_en": "All questions in the survey are closed-ended.",
        "example_rw": "Ibibazo byose biri mu bwoko bw'ibibazo ntangamahitamo y'ibisubizo.",
        "etymology": "'Ntangamahitamo y'ibisubizo' = 'that gives choices of answers.' A functional translation — translates what the format DOES, not the literal meaning of 'closed-ended.' Expert-level localization.",
        "category": "Research Methodology"
    },
    {
        "english": "Ethical approval",
        "kinyarwanda": "Uburenganzira nyemezabushakashatsi",
        "example_en": "The project received ethical approval from the UGHE IRB.",
        "example_rw": "Ubushakashatsi bwahawe uburenganzira nyemezabushakashatsi na UGHE.",
        "etymology": "'Uburenganzira' = rights/authorization. 'Nyemezabushakashatsi' = nyemeza (approve) + ubushakashatsi (research). Frames ethical approval as rights-based authorization.",
        "category": "Research Methodology"
    },
    {
        "english": "Institutional Review Board",
        "kinyarwanda": "Itsinda ngenzurabushakashatsi",
        "example_en": "The IRB reviewed and approved the research protocol.",
        "example_rw": "Itsinda ngenzurabushakashatsi ryasuzumye kandi ryemeza ubushakashatsi.",
        "etymology": "'Itsinda' = group/committee. 'Ngenzurabushakashatsi' = ngenzura (oversee/review) + ubushakashatsi (research). 'The group that oversees research.'",
        "category": "Research Methodology"
    },
    {
        "english": "Informed consent",
        "kinyarwanda": "Itangaburenganzira ku itangamakuru mu bushakashatsi",
        "example_en": "Informed consent must be obtained before any research procedures begin.",
        "example_rw": "Itangaburenganzira ku itangamakuru mu bushakashatsi rigomba kubanza guhabwa.",
        "etymology": "'Itangaburenganzira' = itanga (giving) + uburenganzira (rights). 'Ku itangamakuru' = regarding information-giving. Captures the dual nature of informed consent — both giving rights AND being informed.",
        "category": "Research Ethics"
    },
    {
        "english": "Consent form",
        "kinyarwanda": "Inyandikomvugo ntangaburenganzira",
        "example_en": "Please read the consent form carefully before signing.",
        "example_rw": "Nyabuneka soma inyandikomvugo ntangaburenganzira witonze mbere yo gushyiraho umukono.",
        "etymology": "'Inyandikomvugo' = inyandiko (writing) + mvugo (speech/statement). 'Ntangaburenganzira' = that gives rights. 'Written statement that gives rights.'",
        "category": "Research Ethics"
    },
    {
        "english": "Voluntary participation",
        "kinyarwanda": "Kwitabira ku bushake busesuye",
        "example_en": "Participation in this study is entirely voluntary.",
        "example_rw": "Kwitabira ubu bushakashatsi ni ku bushake busesuye.",
        "etymology": "'Kwitabira' = to participate. 'Ku bushake' = by willingness. 'Busesuye' = complete/full. The intensifier is legally important — emphasizes consent must be complete and uncoerced.",
        "category": "Research Ethics"
    },
    {
        "english": "Witness",
        "kinyarwanda": "Umutangabuhamya",
        "example_en": "A witness must sign the consent form alongside the participant.",
        "example_rw": "Umutangabuhamya agomba gushyira umukono ku nyandikomvugo ntangaburenganzira.",
        "etymology": "'Umutangabuhamya' = u-mu-tanga (one who gives) + ubuhamya (testimony). 'One who gives testimony.' Parallels umutangamakuru (participant).",
        "category": "Research Ethics"
    },
    {
        "english": "Signature",
        "kinyarwanda": "Umukono",
        "example_en": "Your signature indicates your consent to participate.",
        "example_rw": "Umukono wawe urerekana ko wemeye kugira uruhare.",
        "etymology": "'Umukono' literally means 'hand.' This metonymy — where the hand stands for the mark it makes — is ancient in Kinyarwanda.",
        "category": "Research Ethics"
    },
    {
        "english": "Confidentiality",
        "kinyarwanda": "Ibanga",
        "example_en": "All participant data will be kept confidential.",
        "example_rw": "Amakuru yose y'abagize uruhare azagumizwa mu ibanga.",
        "etymology": "'Ibanga' means secret or confidential matter. It carries deep cultural weight — ibanga implies a sacred trust, not just data privacy.",
        "category": "Research Ethics"
    },
    {
        "english": "Password",
        "kinyarwanda": "Ijambobanga",
        "example_en": "Data will be stored on a password-protected computer.",
        "example_rw": "Amakuru azabikwa muri mudasobwa irinzwe n'ijambobanga.",
        "etymology": "'Ijambobanga' = ijambo (word) + ibanga (secret). 'Word of secrecy.' Part of a productive Kinyarwanda pattern where tech terms are built from transparent components.",
        "category": "Technology"
    },
    {
        "english": "Computer",
        "kinyarwanda": "Mudasobwa",
        "example_en": "The collected data will be stored in a password-protected computer.",
        "example_rw": "Amakuru yakusanyijwe azabikwa muri mudasobwa irinzwe n'ijambobanga.",
        "etymology": "'Mudasobwa' = mu-da-sobwa — 'that which does not make errors.' Negative prefix da- on sobwa (to err). An etymologically transparent coinage reflecting an idealized view of computing.",
        "category": "Technology"
    },
    {
        "english": "Compensation",
        "kinyarwanda": "Impozamarira / Inshumbuho / Igihembo",
        "example_en": "Participants will not receive compensation for taking part in this study.",
        "example_rw": "Nta gihembo giteganijwe mu kugira uruhare muri ubu bushakashatsi.",
        "etymology": "Three types: 'impozamarira' (legal/financial for damages), 'inshumbuho' (restitution/repayment), 'igihembo' (reward/payment). Context determines the choice — igihembo for research participation, impozamarira for injury compensation.",
        "category": "Research Ethics"
    },
    {
        "english": "To withdraw from a study",
        "kinyarwanda": "Guhagarika uruhare",
        "example_en": "You may withdraw from the study at any time without penalty.",
        "example_rw": "Ushobora guhagarika uruhare rwawe igihe icyo ari cyo cyose nta nkurikizi.",
        "etymology": "'Guhagarika' = to stop/cease. 'Uruhare' = role/part. Active voice emphasizes participant agency. Alternative passive 'kuvanwa' (to be removed) exists for researcher-initiated withdrawal.",
        "category": "Research Ethics"
    },
    {
        "english": "Copy (of document)",
        "kinyarwanda": "Impanga-shusho",
        "example_en": "You will receive a signed copy of this consent form.",
        "example_rw": "Uraza gushyikirizwa impanga-shusho iriho itariki n'umukono by'iyi fishi.",
        "etymology": "'Impanga-shusho' = impanga (replica/duplicate) + ishusho (image/likeness). 'Image replica.' A relatively new neologism — the English 'copy' is still sometimes used alongside it in parentheses.",
        "category": "Administrative"
    },
    {
        "english": "Ministry of Health",
        "kinyarwanda": "Minisiteri y'ubuzima",
        "example_en": "The results will inform decision-making within the Ministry of Health.",
        "example_rw": "Ibizava muri ubu bushakashatsi bizafasha mu ifatwa ry'ibyemezo muri Minisiteri y'ubuzima.",
        "etymology": "'Minisiteri' borrowed from French 'ministère.' 'Y'ubuzima' = of health. Standard French institutional borrowing with Kinyarwanda possessive for government terminology.",
        "category": "Institutional"
    },
    {
        "english": "Partners in Health",
        "kinyarwanda": "Inshuti Mu Buzima (IMB)",
        "example_en": "This study is being carried out in collaboration with Partners in Health.",
        "example_rw": "Ubu bushakashatsi buri gukorwa ku bufatanye n'umuryango w'Inshuti Mu Buzima.",
        "etymology": "'Inshuti' = friends/partners. 'Mu Buzima' = in health. A semantic translation of the organization name — not phonetic borrowing. IMB is used alongside PIH in official documents.",
        "category": "Institutional"
    },
    {
        "english": "University of Global Health Equity",
        "kinyarwanda": "Kaminuza iharanira uburinganire mu isigasirabuzima ku isi",
        "example_en": "The study was conducted under the auspices of UGHE.",
        "example_rw": "Ubushakashatsi bwakorerwe mu rwego rwa kaminuza iharanira uburinganire mu isigasirabuzima ku isi.",
        "etymology": "'Kaminuza' (university, from French). 'Iharanira' = that strives for. 'Uburinganire' = equality/equity. 'Mu isigasirabuzima ku isi' = in global health. Every word is translated semantically, making the institution's mission immediately clear.",
        "category": "Institutional"
    },
]


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # Create admin if not exists
        if not Admin.query.filter_by(username=ADMIN_USERNAME).first():
            admin = Admin(username=ADMIN_USERNAME)
            admin.set_password(ADMIN_PASSWORD)
            db.session.add(admin)
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
        print(f"\n⚠ Remember to change the admin password in seed_data.py!")
        print(f"⚠ Admin login: /admin/login")


if __name__ == "__main__":
    seed()
