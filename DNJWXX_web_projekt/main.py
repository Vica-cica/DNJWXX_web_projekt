import os
import datetime as dt
from fastapi import FastAPI, Depends, HTTPException, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, Integer, String, create_engine, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship, joinedload

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

class Borrow(Base):
    __tablename__ = "borrows"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    borrowed_at = Column(String, default=lambda: dt.datetime.now().strftime("%Y-%m-%d %H:%M"))

    # Kapcsolatok, hogy könnyen elérjük a könyv adatait a kölcsönzésen keresztül
    user = relationship("User")
    book = relationship("Book")

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
def read_root(request: Request, db: Session = Depends(get_db)):
    real_books = db.query(Book).order_by(Book.title.asc()).all()
    current_user = get_current_user(request, db)
    
    user_borrows = []
    all_borrows = []
    
    if current_user:
        # A felhasználó saját kölcsönzései
        user_borrows = db.query(Borrow).filter(Borrow.user_id == current_user.id).all()
        
        # Ha admin az illető, akkor az ÖSSZES kölcsönzést lekérjük, 
        # kényszerítve az adatbázist, hogy a kapcsolódó User és Book adatokat is azonnal adja át!
        if current_user.is_admin:
            all_borrows = db.query(Borrow).options(
                joinedload(Borrow.user),
                joinedload(Borrow.book)
            ).all()

    return templates.TemplateResponse(
        "konyvtar.html", 
        {
            "request": request, 
            "user": current_user, 
            "books": real_books,
            "user_borrows": user_borrows,
            "all_borrows": all_borrows
        }
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
    db.refresh(new_user)
    
    # Token létrehozása
    access_token = create_access_token(data={"sub": new_user.username})
    
    # Átirányítás a főoldalra úgy, hogy elmentjük a tokent egy sütibe (Cookie)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

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
            Book(title="Egri Csillagok", author="Gárdonyi Géza", imageUrl="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSfw4mHNR1JQ8VRSFkrJVad8AW4a5_TEssojA&s", total_copies=5, available_copies=5),
            Book(title="A Pál utcai fiúk", author="Molnár Ferenc", imageUrl="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSJPwlDenA55v55CJDP_0UMJuNU_lUQn7e22g&s", total_copies=5, available_copies=5),
            Book(title="1984", author="George Orwell", imageUrl="https://encrypted-tbn3.gstatic.com/shopping?q=tbn:ANd9GcSjltxoQGnSMQqRbsemjM9qxO8f7ZFzGPraYI9Qg7YkwAKtMALY6Pk5j-0VDB5pCurftZZhSD82wGSc5jGxi3LkF747rqRKMI6AmAyxITCi&usqp=CAc", total_copies=2, available_copies=2)
        ]
        db.add_all(default_books)
        db.commit()
    db.close()

@app.post("/books/add")
def add_book(
    title: str = Form(...), 
    author: str = Form(...), 
    imageUrl: str = Form(None), 
    copies: int = Form(...), 
    db: Session = Depends(get_db),
    request: Request = None
):
    # Ellenőrizzük, hogy valóban az admin (Vuka) akarja-e hozzáadni
    current_user = get_current_user(request, db)
    if not current_user or not current_user.is_admin:
        return RedirectResponse(url="/?error=nincs_jogosultsag", status_code=303)

    # Ha nem adott meg képet, teszünk be egy alapértelmezett könyvborítót
    if not imageUrl or imageUrl.strip() == "":
        imageUrl = "https://picsum.photos/id/24/200/300"

    # Létrehozzuk az új könyvet az adatbázisban
    new_book = Book(
        title=title, 
        author=author, 
        imageUrl=imageUrl, 
        total_copies=copies, 
        available_copies=copies
    )
    db.add(new_book)
    db.commit()
    
    return RedirectResponse(url="/", status_code=303)


# 2. KÖNYV TÖRLÉSE (ADMIN FELÜLET)
@app.post("/books/{book_id}/delete")
def delete_book(book_id: int, db: Session = Depends(get_db), request: Request = None):
    # Biztonsági ellenőrzés (csak admin jöhet be)
    current_user = get_current_user(request, db)
    if not current_user or not current_user.is_admin:
        return RedirectResponse(url="/?error=nincs_jogosultsag", status_code=303)

    # 1. ELLENŐRZÉS: Ki van-e kölcsönözve a könyv éppen?
    # Megnézzük, hogy az összes példányszám megegyezik-e az elérhetővel.
    # Ha az elérhető kevesebb, az azt jelenti, hogy valakinél ott van!
    book = db.query(Book).filter(Book.id == book_id).first()
    
    if book:
        if book.available_copies < book.total_copies:
            # Ha ki van kölcsönözve, nem engedjük törölni, visszadobjuk egy hibaüzenettel
            return RedirectResponse(url="/?error=konyv_kint_van", status_code=303)
        
        # 2. Ha nincs kikölcsönözve, akkor biztonságosan törölhetjük
        db.delete(book)
        db.commit()
        
    return RedirectResponse(url="/", status_code=303)

@app.post("/books/{book_id}/update_copies")
def update_book_copies(
    book_id: int, 
    total_copies: int = Form(...), 
    db: Session = Depends(get_db), 
    request: Request = None
):
    # Biztonsági ellenőrzés: csak az admin (Vuka) jöhet be ide
    current_user = get_current_user(request, db)
    if not current_user or not current_user.is_admin:
        return RedirectResponse(url="/?error=nincs_jogosultsag", status_code=303)

    book = db.query(Book).filter(Book.id == book_id).first()
    if book:
        # Kiszámoljuk, hogy jelenleg hány darab van kikölcsönözve belőle
        currently_borrowed = book.total_copies - book.available_copies
        
        # Nem engedhetjük, hogy az új darabszám kevesebb legyen, mint ahány darab épp kint van az olvasóknál!
        if total_copies < currently_borrowed:
            return RedirectResponse(url=f"/?error=kevesebb_mint_a_kolcsonzott", status_code=303)

        # Frissítjük a darabszámokat
        book.total_copies = total_copies
        book.available_copies = total_copies - currently_borrowed
        
        db.commit()
        
    return RedirectResponse(url="/", status_code=303)

# 3. KÖNYV KÖLCSÖNZÉSE
@app.post("/books/{book_id}/borrow")
def borrow_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/?error=be_kell_jelentkezni", status_code=303)

    book = db.query(Book).filter(Book.id == book_id).first()
    if book and book.available_copies > 0:
        # 1. Csökkentjük a szabad példányokat
        book.available_copies -= 1
        
        # 2. Elmentjük a kölcsönzési tényt
        new_borrow = Borrow(user_id=current_user.id, book_id=book.id)
        db.add(new_borrow)
        
        db.commit()
        
    return RedirectResponse(url="/", status_code=303)


# 4. KÖNYV VISSZAHOZATALA
@app.post("/books/{book_id}/return")
def return_book(book_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/?error=be_kell_jelentkezni", status_code=303)

    # Megkeressük azt a kölcsönzést, ami EHHEZ a felhasználóhoz ÉS EHHEZ a könyvhöz tartozik
    borrow_record = db.query(Borrow).filter(
        Borrow.user_id == current_user.id,
        Borrow.book_id == book_id
    ).first()

    # Ha nem találtunk ilyen bejegyzést, akkor a felhasználónál nincs is ilyen könyv!
    if not borrow_record:
        return RedirectResponse(url="/?error=ez_a_konyv_nincs_nalad", status_code=303)

    book = db.query(Book).filter(Book.id == book_id).first()
    if book:
        # 1. Visszatesszük a könyvet a polcra (növeljük az elérhető példányszámot)
        book.available_copies += 1
        
        # 2. TÖRÖLJÜK a kölcsönzési rekordot a borrows táblából, hiszen visszahozta
        db.delete(borrow_record)
        
        db.commit()
        
    return RedirectResponse(url="/", status_code=303)

app.mount("/static", StaticFiles(directory="."), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)