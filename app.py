import os
import uuid
import json
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import libsql_client  # <-- Turso bulut veritabanı motoru eklendi

load_dotenv()

app = Flask(__name__)

_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise ValueError("SECRET_KEY ortam değişkeni tanımlı değil. .env dosyasını kontrol edin.")
app.secret_key = _secret_key

app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB dosya boyutu limiti
app.config['WTF_CSRF_ENABLED'] = True

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[]
)

_admin_password = os.environ.get('ADMIN_PASSWORD')
if not _admin_password:
    raise ValueError("ADMIN_PASSWORD ortam değişkeni tanımlı değil. .env dosyasını kontrol edin.")


# ── TURSO BULUT BAĞLANTISI ──────────────────────────────
def db_connect():
    url = os.environ.get('TURSO_DATABASE_URL')
    token = os.environ.get('TURSO_AUTH_TOKEN')
    
    # Vercel'de URL varsa buluta bağlan, yoksa local test için bilgisayardaki dosyaya bağlan
    if url and token:
        return libsql_client.create_client_sync(url=url, auth_token=token)
    else:
        return libsql_client.create_client_sync(url="file:database.db")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_db():
    with db_connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS projeler
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      baslik TEXT NOT NULL,
                      aciklama TEXT NOT NULL,
                      resim TEXT NOT NULL,
                      yil INTEGER,
                      ozellikler TEXT DEFAULT '')''')

        # libsql_client'ta satırlara liste gibi erişilir
        pragmas = conn.execute('PRAGMA table_info(projeler)').rows
        mevcut_kolonlar = {row[1] for row in pragmas}  # 1. index 'name' kolonudur
        
        if 'yil' not in mevcut_kolonlar:
            conn.execute('ALTER TABLE projeler ADD COLUMN yil INTEGER')
        if 'ozellikler' not in mevcut_kolonlar:
            conn.execute("ALTER TABLE projeler ADD COLUMN ozellikler TEXT DEFAULT ''")

        # Takım üyeleri tablosu
        conn.execute('''CREATE TABLE IF NOT EXISTS uyeler
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      isim TEXT NOT NULL,
                      gorev TEXT NOT NULL,
                      departman TEXT NOT NULL,
                      linkedin TEXT DEFAULT '',
                      foto TEXT DEFAULT '')''')

        # Sponsorlar tablosu
        conn.execute('''CREATE TABLE IF NOT EXISTS sponsorlar
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      isim TEXT NOT NULL,
                      kademe TEXT NOT NULL,
                      logo TEXT DEFAULT '')''')

        # İletişim mesajları tablosu
        conn.execute('''CREATE TABLE IF NOT EXISTS iletisim_mesajlari
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ad_soyad TEXT NOT NULL,
                      eposta TEXT NOT NULL,
                      mesaj TEXT NOT NULL,
                      tarih TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

        # Başlangıç verileri kontrolü
        rs = conn.execute('SELECT COUNT(*) as toplam FROM projeler')
        proje_sayisi = rs.rows[0][0]
        
        if proje_sayisi == 0:
            conn.execute(
                '''INSERT INTO projeler (baslik, aciklama, resim, yil, ozellikler)
                   VALUES (?, ?, ?, ?, ?)''',
                (
                    'İnsansız Denizaltı',
                    'Otonom görev kabiliyetine sahip, sensör füzyonu ile su altı keşif ve analiz yapan platform.',
                    'c358d37142044c49aaf9b5934e0d5538.jpg',
                    2026,
                    'Otonom rota takibi\nGerçek zamanlı telemetri\nDerinlik ve engel algılama\nModüler görev mimarisi'
                )
            )
            conn.execute(
                '''INSERT INTO projeler (baslik, aciklama, resim, yil, ozellikler)
                   VALUES (?, ?, ?, ?, ?)''',
                (
                    'Hava Savunma',
                    'Akıllı hedef takip algoritmaları ve hızlı karar mekanizmasıyla sahada aktif savunma yaklaşımı.',
                    'F65oe61WcAEmJvr.jpg',
                    2026,
                    'Görüntü işleme destekli hedef analizi\nYüksek hızlı karar döngüsü\nDağıtık kontrol altyapısı\nSimülasyon destekli test süreci'
                )
            )
        # conn.commit() kaldırıldı, çünkü libsql_client işlemleri otomatik uygular.


init_db()


def get_projects():
    with db_connect() as conn:
        rows = conn.execute('SELECT * FROM projeler ORDER BY COALESCE(yil, 0) DESC, id DESC').rows

    projects = []
    for row in rows:
        ozellikler = row["ozellikler"] or ''
        projects.append({
            'id': row["id"],
            'baslik': row["baslik"],
            'aciklama': row["aciklama"],
            'resim': row["resim"],
            'yil': row["yil"],
            'ozellikler': [x.strip() for x in ozellikler.split('\n') if x.strip()]
        })
    return projects


@app.route('/')
def ana_sayfa():
    projeler = get_projects()
    return render_template('index.html', one_cikan_projeler=projeler[:2])


@app.route('/takimimiz')
def takimimiz():
    with db_connect() as conn:
        rows = conn.execute('SELECT * FROM uyeler ORDER BY departman, id').rows
        
    uyeler = []
    for r in rows:
        uyeler.append({
            'id': r["id"],
            'isim': r["isim"],
            'gorev': r["gorev"],
            'departman': r["departman"],
            'linkedin': r["linkedin"],
            'foto': r["foto"]
        })
    return render_template('takimimiz.html', uyeler=uyeler, admin=session.get('giris_yapildi', False))


# ── Üye API route'ları (sadece admin) ──────────────────────────────
@app.route('/api/uye/ekle', methods=['POST'])
def uye_ekle():
    if not session.get('giris_yapildi'):
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    isim    = request.form.get('isim', '').strip()
    gorev   = request.form.get('gorev', '').strip()
    dept    = request.form.get('departman', '').strip()
    linkedin = request.form.get('linkedin', '').strip()
    if not isim or not gorev or not dept:
        return jsonify({'ok': False, 'error': 'Eksik alan'}), 400

    foto_adi = ''
    foto_dosya = request.files.get('foto')
    if foto_dosya and foto_dosya.filename and allowed_file(foto_dosya.filename):
        ext = foto_dosya.filename.rsplit('.', 1)[1].lower()
        foto_adi = uuid.uuid4().hex + '.' + ext
        # Vercel Salt-Okunur Koruması (Hata vermesini önler)
        try:
            foto_dosya.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_adi))
        except Exception:
            pass 

    with db_connect() as conn:
        rs = conn.execute(
            'INSERT INTO uyeler (isim, gorev, departman, linkedin, foto) VALUES (?,?,?,?,?)',
            (isim, gorev, dept, linkedin, foto_adi)
        )
        new_id = rs.last_insert_rowid
    return jsonify({'ok': True, 'id': new_id, 'foto': foto_adi})


@app.route('/api/uye/guncelle/<int:uid>', methods=['POST'])
def uye_guncelle(uid):
    if not session.get('giris_yapildi'):
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    isim    = request.form.get('isim', '').strip()
    gorev   = request.form.get('gorev', '').strip()
    dept    = request.form.get('departman', '').strip()
    linkedin = request.form.get('linkedin', '').strip()
    if not isim or not gorev or not dept:
        return jsonify({'ok': False, 'error': 'Eksik alan'}), 400

    with db_connect() as conn:
        mevcut = conn.execute('SELECT foto FROM uyeler WHERE id=?', (uid,)).rows
        if not mevcut:
            return jsonify({'ok': False, 'error': 'Bulunamadı'}), 404
        foto_adi = mevcut[0]['foto']
        foto_dosya = request.files.get('foto')
        if foto_dosya and foto_dosya.filename and allowed_file(foto_dosya.filename):
            ext = foto_dosya.filename.rsplit('.', 1)[1].lower()
            foto_adi = uuid.uuid4().hex + '.' + ext
            try:
                foto_dosya.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_adi))
            except Exception:
                pass
                
        conn.execute(
            'UPDATE uyeler SET isim=?, gorev=?, departman=?, linkedin=?, foto=? WHERE id=?',
            (isim, gorev, dept, linkedin, foto_adi, uid)
        )
    return jsonify({'ok': True, 'foto': foto_adi})


@app.route('/api/uye/sil/<int:uid>', methods=['POST'])
def uye_sil(uid):
    if not session.get('giris_yapildi'):
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    with db_connect() as conn:
        conn.execute('DELETE FROM uyeler WHERE id=?', (uid,))
    return jsonify({'ok': True})


# ── İletişim API route'ları ──────────────────────────────
@app.route('/api/iletisim', methods=['POST'])
@limiter.limit("5 per minute")
def iletisim_post():
    data = request.get_json()
    if not data:
        return jsonify({'ok': False, 'error': 'Geçersiz veri formatı'}), 400
    
    ad_soyad = data.get('ad_soyad', '').strip()
    eposta = data.get('eposta', '').strip()
    mesaj = data.get('mesaj', '').strip()
    
    if not ad_soyad or not eposta or not mesaj:
        return jsonify({'ok': False, 'error': 'Gerekli alanlar eksik'}), 400

    with db_connect() as conn:
        conn.execute(
            'INSERT INTO iletisim_mesajlari (ad_soyad, eposta, mesaj) VALUES (?, ?, ?)',
            (ad_soyad, eposta, mesaj)
        )
    return jsonify({'ok': True})

@app.route('/api/iletisim/sil/<int:mid>', methods=['POST'])
def iletisim_sil(mid):
    if not session.get('giris_yapildi'):
        return jsonify({'ok': False, 'error': 'Yetkisiz'}), 403
    with db_connect() as conn:
        conn.execute('DELETE FROM iletisim_mesajlari WHERE id=?', (mid,))
    return jsonify({'ok': True})


@app.route('/projelerimiz')
def projelerimiz():
    projeler = get_projects()
    return render_template('projelerimiz.html', projeler=projeler)


@app.route('/basarilarimiz')
def basarilarimiz():
    return render_template('basarilarimiz.html')


@app.route('/iletisim')
def iletisim():
    return render_template('iletisim.html')


@app.route('/admin', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def admin():
    if request.method == 'POST':
        if 'sifre' in request.form:
            if request.form['sifre'] == _admin_password:
                session['giris_yapildi'] = True
            return redirect(url_for('admin'))

        if session.get('giris_yapildi') and 'baslik' in request.form:
            baslik = request.form['baslik']
            aciklama = request.form['aciklama']
            yil_raw = request.form.get('yil', '').strip()
            yil = int(yil_raw) if yil_raw.isdigit() else None
            ozellikler = request.form.get('ozellikler', '').strip()
            resim_dosyasi = request.files.get('resim')
            resim_adi = ''

            if resim_dosyasi and allowed_file(resim_dosyasi.filename):
                ext = resim_dosyasi.filename.rsplit('.', 1)[1].lower()
                resim_adi = uuid.uuid4().hex + '.' + ext
                try:
                    resim_dosyasi.save(os.path.join(app.config['UPLOAD_FOLDER'], resim_adi))
                except Exception:
                    pass
            
            with db_connect() as conn:
                conn.execute(
                    'INSERT INTO projeler (baslik, aciklama, resim, yil, ozellikler) VALUES (?, ?, ?, ?, ?)',
                    (baslik, aciklama, resim_adi, yil, ozellikler)
                )
            return redirect(url_for('admin'))

    projeler = get_projects()
    with db_connect() as conn:
        mesajlar_rows = conn.execute('SELECT * FROM iletisim_mesajlari ORDER BY id DESC').rows
    
    mesajlar = []
    for r in mesajlar_rows:
        mesajlar.append({
            'id': r["id"],
            'ad_soyad': r["ad_soyad"],
            'eposta': r["eposta"],
            'mesaj': r["mesaj"],
            'tarih': r["tarih"]
        })

    return render_template('admin.html', projeler=projeler, mesajlar=mesajlar)


# Proje Silme Rotası
@app.route('/sil/<int:id>', methods=['POST'])
def sil(id):
    if not session.get('giris_yapildi'):
        return redirect(url_for('admin'))

    with db_connect() as conn:
        conn.execute('DELETE FROM projeler WHERE id = ?', (id,))
    return redirect(url_for('admin'))


# Proje Düzenleme Rotası
@app.route('/duzenle/<int:id>', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
def duzenle(id):
    if not session.get('giris_yapildi'):
        return redirect(url_for('admin'))

    if request.method == 'POST':
        baslik = request.form['baslik']
        aciklama = request.form['aciklama']
        yil_raw = request.form.get('yil', '').strip()
        yil = int(yil_raw) if yil_raw.isdigit() else None
        ozellikler = request.form.get('ozellikler', '').strip()
        resim_dosyasi = request.files.get('resim')

        with db_connect() as conn:
            mevcut = conn.execute('SELECT resim FROM projeler WHERE id = ?', (id,)).rows
            if not mevcut:
                return redirect(url_for('admin'))

            resim_adi = mevcut[0]['resim']
            if resim_dosyasi and resim_dosyasi.filename and allowed_file(resim_dosyasi.filename):
                ext = resim_dosyasi.filename.rsplit('.', 1)[1].lower()
                resim_adi = uuid.uuid4().hex + '.' + ext
                try:
                    resim_dosyasi.save(os.path.join(app.config['UPLOAD_FOLDER'], resim_adi))
                except Exception:
                    pass

            conn.execute(
                'UPDATE projeler SET baslik = ?, aciklama = ?, resim = ?, yil = ?, ozellikler = ? WHERE id = ?',
                (baslik, aciklama, resim_adi, yil, ozellikler, id)
            )
        return redirect(url_for('admin'))

    with db_connect() as conn:
        rs = conn.execute('SELECT * FROM projeler WHERE id = ?', (id,)).rows
    
    if not rs:
        return redirect(url_for('admin'))
        
    r = rs[0]
    proje = {
        'id': r["id"],
        'baslik': r["baslik"],
        'aciklama': r["aciklama"],
        'resim': r["resim"],
        'yil': r["yil"],
        'ozellikler': r["ozellikler"]
    }
    return render_template('duzenle.html', proje=proje)


@app.route('/logout')
def logout():
    session.pop('giris_yapildi', None)
    return redirect(url_for('ana_sayfa'))


if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode)