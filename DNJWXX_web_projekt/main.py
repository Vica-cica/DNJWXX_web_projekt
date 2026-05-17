import os
import datetime
from fastapi import FastAPI, Depends, HTTPException, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

### biztonsagi beallitas###
SECRET_KEY = os.environ.get("LIBRARY_SECRET_KEY", "szuper_titkos_kulcs_amit_ki_kell_cserelni")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

###jelszo titkositas###
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

### database beallitas###
DATABASE_URL = "postgresql://library_user:library_password@localhost:5432/library_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

###database modell###

class Book(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    imageUrl = Column(String, nullable=True)
    total_copies = Column(Integer, default=1)
    available_copies = Column(Integer, default=1)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Online Könyvtár és Kölcsönző API")

templates = Jinja2Templates(directory=".")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return db.query(User).filter(User.username == username).first()
    except InvalidTokenError:
        return None

def create_access_token(data: dict):
    to_encode = data.copy()
    
    # Közvetlenül a beépített datetime modult és timezone-t hívjuk meg, garantáltan hiba nélkül
    import datetime as dt
    expire = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    if isinstance(encoded_jwt, bytes):
        return encoded_jwt.decode("utf-8")
    return encoded_jwt

@app.get("/")
def read_root(request:Request, db: Session = Depends(get_db)):
    real_books = db.query(Book).all()
    current_user = get_current_user(request, db)

    return templates.TemplateResponse(
        "konyvtar.html", 
        {"request": request, "user": current_user, "books": real_books}
    )

@app.post("/auth/register")
def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    # Ellenőrizzük, létezik-e már a név
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        return RedirectResponse(url="/?error=foglalt_nev", status_code=303)
    
    # Új felhasználó mentése lehashelt jelszóval
    hashed_pwd = pwd_context.hash(password)
    new_user = User(username=username, hashed_password=hashed_pwd, is_admin=False)
    db.add(new_user)
    db.commit()
    
    return RedirectResponse(url="/?success=sikeres_regisztracio", status_code=303)

# BEJELENTKEZÉS LEKEZELÉSE
@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    
    # Felhasználó és jelszó ellenőrzése
    if not user or not pwd_context.verify(password, user.hashed_password):
        return RedirectResponse(url="/?error=hibas_adatok", status_code=303)
    
    # Token létrehozása
    access_token = create_access_token(data={"sub": user.username})
    
    # Átirányítás a főoldalra úgy, hogy elmentjük a tokent egy sütibe (Cookie)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

# KIJELENTKEZÉS LEKEZELÉSE
@app.get("/auth/logout")
def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="access_token")  # Töröljük a belépési sütit
    return response

app.mount("/", StaticFiles(directory="."), name="static")

@app.on_event("startup")
def setup_default_data():
    db = SessionLocal()
    admin_user = db.query(User).filter(User.username == "Vuka").first()
    if not admin_user:
        hashed_admin_pwd = pwd_context.hash("piri2015")
        vuka_admin = User(username="Vuka", hashed_password=hashed_admin_pwd, is_admin=True)
        db.add(vuka_admin)
        db.commit()

    if db.query(Book).count() == 0:
        default_books = [
            Book(title="Egri Csillagok", author="Gárdonyi Géza", imageUrl="https://picsum.photos/id/24/200/300", total_copies=5, available_copies=5),
            Book(title="A Pál utcai fiúk", author="Molnár Ferenc", imageUrl="https://picsum.photos/id/39/200/300", total_copies=3, available_copies=2),
            Book(title="1984", author="George Orwell", imageUrl="https://picsum.photos/id/48/200/300", total_copies=2, available_copies=0)
        ]
        db.add_all(default_books)
        db.commit()
    db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)