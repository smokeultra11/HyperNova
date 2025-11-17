from flask import Blueprint, request, render_template_string, redirect, url_for
from database import get_db_connection, grant_premium, is_user_premium, check_admin_auth
import logging

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__)

def admin_login_template(error=""):
    return render_template_string(f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head><title>Admin Giriş</title>
    <style>body {{ font-family: sans-serif; background: #f0f4f8; display: flex; justify-content: center; align-items: center; height: 100vh; }} .login-box {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); width: 350px; }} input {{ width: 100%; padding: 12px; margin-bottom: 20px; border: 1px solid #ccc; border-radius: 8px; }} button {{ width: 100%; padding: 12px; background: #4f46e5; color: white; border: none; border-radius: 8px; cursor: pointer; }} .error {{ color: #ef4444; }}</style>
    </head>
    <body>
        <div class="login-box">
            <h2>Admin Giriş</h2>
            {f'<div class="error">{error}</div>' if error else ''}
            <form method="POST">
                <input type="hidden" name="form_type" value="login">
                <input type="text" name="admin_username" placeholder="Kullanıcı Adı" required>
                <input type="password" name="admin_password" placeholder="Şifre" required>
                <button>Giriş</button>
            </form>
        </div>
    </body>
    </html>
    """)

def admin_panel_template(message="", is_authenticated=False):
    if not is_authenticated:
        return redirect(url_for('admin.admin_panel'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, premium_until FROM users ORDER BY premium_until DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    user_list_html = ""
    for row in rows:
        username = row['username']
        status = "AKTİF" if is_user_premium(username) else "PASİF"
        color = "green" if status == "AKTİF" else "red"
        expiry = row['premium_until'].isoformat()
        user_list_html += f'<tr><td>{username}</td><td><span style="color: {color}">{status}</span></td><td>{expiry}</td></tr>'
    return render_template_string(f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head><title>Admin Panel</title>
    <style>body {{ font-family: sans-serif; background: #1f2937; color: #f9fafb; padding: 20px; }} .container {{ max-width: 1000px; margin: auto; background: #374151; padding: 30px; border-radius: 12px; }} h1 {{ color: #8b5cf6; }} form {{ background: #4b5563; padding: 20px; border-radius: 8px; }} input {{ width: 100%; padding: 10px; background: #374151; color: #f9fafb; }} button {{ padding: 10px; background: #8b5cf6; color: white; border: none; }} table {{ width: 100%; border-collapse: collapse; }} th {{ background: #4b5563; color: #facc15; }}</style>
    </head>
    <body>
        <div class="container">
            <h1>Admin Panel</h1>
            {f'<div style="background: #10b981; padding: 15px;">{message}</div>' if message else ''}
            <h2>Premium Ver</h2>
            <form method="POST">
                <input type="hidden" name="form_type" value="premium_grant">
                <input type="text" name="auth_username" placeholder="Admin Kullanıcı" required>
                <input type="password" name="auth_password" placeholder="Admin Şifre" required>
                <input type="text" name="target_username" placeholder="Hedef Kullanıcı" required>
                <button>30 Gün Premium Ver</button>
            </form>
            <h2>Kullanıcılar</h2>
            <table><thead><tr><th>Kullanıcı</th><th>Durum</th><th>Bitiş</th></tr></thead><tbody>{user_list_html or '<tr><td colspan=3>Yok</td></tr>'}</tbody></table>
        </div>
    </body>
    </html>
    """)

@admin_bp.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        if form_type == 'login':
            if check_admin_auth(request.form.get('admin_username'), request.form.get('admin_password')):
                return redirect(url_for('admin.admin_panel', auth='success'))
            return admin_login_template("Geçersiz kimlik")
        elif form_type == 'premium_grant':
            if not check_admin_auth(request.form.get('auth_username'), request.form.get('auth_password')):
                return admin_login_template("Yetkisiz")
            target = request.form.get('target_username')
            if grant_premium(target):
                message = f"{target} premium verildi (30 gün)."
                logger.info(f"Premium: {target}")
            else:
                message = f"Hata: {target} bulunamadı."
            return admin_panel_template(message, True)
    if request.args.get('auth') == 'success':
        return admin_panel_template("", True)
    return admin_login_template()
