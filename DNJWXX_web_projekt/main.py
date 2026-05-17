import os
import datetime
from fastapi import FastAPI, Depends, HTTPException, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import jwt
from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

app = FastAPI(title="Online Könyvtár és Kölcsönző API")

app.mount("/", StaticFiles(directory="."), name="static")

templates = Jinja2Templates(directory=".")

### biztonsagi beallitas###
SECRET_KEY = os.environ.get("LIBRARY_SECRET_KEY", "szuper_titkos_kulcs_amit_ki_kell_cserelni")
ALGORITHM = "HS256"

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload