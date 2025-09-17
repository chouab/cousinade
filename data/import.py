# scripts/import_csv.py
import csv, datetime, secrets
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.models import Base, Member, ParentChild, Couple, EditToken

engine = create_engine("sqlite:///./cousinade.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

def get_or_create_member(db, first, last, birth=None, email=None, phone=None, branch=None):
    m = db.scalar(select(Member).where(Member.first_name==first, 
                                       Member.family_branch==branch,
                                       Member.phone == phone,
                                       Member.email == email
                                       ))

    if not m:
        m = Member(first_name=first, last_name=last)
        db.add(m); db.flush()

    # complète si vide
    if birth and not m.birth_date:
        try: m.birth_date = datetime.datetime.strptime(birth, '%d/%m/%Y').date()
        except Exception as e:
            print(e)

    m.email = m.email or (email or None)
    m.phone = m.phone or (phone or None)
    m.family_branch = m.family_branch or (branch or None)
    return m

with SessionLocal() as db:
    t = db.query(EditToken).all()
    print(t[0].token)

    # cousins = db.query(Member).where((Member.first_name=='David'))  # ou ajoute un filtre si tu veux seulement certains
    # for c in cousins:
    #     token = secrets.token_urlsafe(32)
    #     db.add(EditToken(
    #         token=token,
    #         owner_member_id=c.id,
    #         expires_at=datetime.datetime.now() + datetime.timedelta(days=30)  # valide 30j
    #     ))
    # db.commit()
exit()

with SessionLocal() as db, open("cousins.csv", newline='', encoding="utf-8") as f:
    r = csv.DictReader(f)
    conjoint = False
    for row in r:
        print(row)
        if row['type'] == 'cousin' :
            parent = get_or_create_member(
                db,
                row["prénom"].strip(), 
                row.get("last_name") or ' ',
                row.get("anniversaire") or None,
                row.get("email") or None,
                row.get("téléphone") or None,
                row.get("type") or None
            )
            conjoint = False
        elif row['type'] == 'conjoint' : 
            conjoint = get_or_create_member(
                db,
                row["prénom"].strip(), 
                row.get("last_name") or ' ',
                row.get("anniversaire") or None,
                row.get("email") or None,
                row.get("téléphone") or None,
                row.get("type") or None
            )
            exists = db.scalar(
                select(Couple).where(
                    ((Couple.partner_a_id==parent.id) & (Couple.partner_b_id==conjoint.id)) |
                    ((Couple.partner_a_id==conjoint.id) & (Couple.partner_b_id==parent.id))
                )
            )
            if not exists:
                db.add(Couple(partner_a_id=parent.id, partner_b_id=conjoint.id, status="current"))

        elif row['type'] == 'enfant' : 
            enfant = get_or_create_member(
                db,
                row["prénom"].strip(), 
                row.get("last_name") or ' ',
                row.get("anniversaire") or None,
                row.get("email") or None,
                row.get("téléphone") or None,
                row.get("type") or None
            )
            if not db.scalar(select(ParentChild).where(ParentChild.parent_id==parent.id, ParentChild.child_id==enfant.id)):
                db.add(ParentChild(parent_id=parent.id, child_id=enfant.id))
            if conjoint :    
                if not db.scalar(select(ParentChild).where(ParentChild.parent_id==conjoint.id, ParentChild.child_id==enfant.id)):
                    db.add(ParentChild(parent_id=conjoint.id, child_id=enfant.id))

        elif row['type'] == 'enfant-conjoint' : 
            enfant_conjoint = get_or_create_member(
                db,
                row["prénom"].strip(), 
                row.get("last_name") or ' ',
                row.get("anniversaire") or None,
                row.get("email") or None,
                row.get("téléphone") or None,
                row.get("type") or None
            )
            exists = db.scalar(
                select(Couple).where(
                    ((Couple.partner_a_id==enfant.id) & (Couple.partner_b_id==enfant_conjoint.id)) |
                    ((Couple.partner_a_id==enfant_conjoint.id) & (Couple.partner_b_id==enfant.id))
                )
            )
            if not exists:
                db.add(Couple(partner_a_id=enfant.id, partner_b_id=enfant_conjoint.id, status="current"))

        elif row['type'] == 'petit-enfant' : 
            penfant = get_or_create_member(
                db,
                row["prénom"].strip(), 
                row.get("last_name") or ' ',
                row.get("anniversaire") or None,
                row.get("email") or None,
                row.get("téléphone") or None,
                row.get("type") or None
            )
            if not db.scalar(select(ParentChild).where(ParentChild.parent_id==enfant.id, ParentChild.child_id==penfant.id)):
                db.add(ParentChild(parent_id=enfant.id, child_id=penfant.id))
            if enfant_conjoint :    
                if not db.scalar(select(ParentChild).where(ParentChild.parent_id==enfant_conjoint.id, ParentChild.child_id==penfant.id)):
                    db.add(ParentChild(parent_id=enfant_conjoint.id, child_id=penfant.id))

        db.commit()
print("Import terminé.")
