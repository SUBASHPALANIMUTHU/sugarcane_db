# ======================================
#   Sugarcane Transcriptome Web App
#   Clean Bootstrap Dashboard Version
# ======================================

import os
import math

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    make_response,
    abort,
    flash,
)
import psycopg


# -------------------------------
#  Flask app & configuration
# -------------------------------
app = Flask(__name__)
app.secret_key = "change-this-secret-for-flash-messages"

# IMPORTANT: %23 = '#' in URL encoding
DB_URL = os.getenv("DATABASE_URL")  # Render injects this automatically

RESULTS_PER_PAGE = 20

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Simple admin token for upload page (only you should know this)
ADMIN_TOKEN = "subash_admin_only_change_this"

# Global author details for footer
AUTHOR_INFO = {
    "creator_name": "Subash Palanimuthu, Bioinformatician",
    "supervisor_name": "Dr. Prathima P.T, Principal Scientist",
    "institute": "Department of Biotechnology<br>ICAR–Sugarcane Breeding Institute,Coimbatore",
}

creator_photo = "/static/creator.jpg"        # You will upload this
supervisor_photo = "/static/supervisor.jpg"  # You will upload this

# -------------------------------
#  Context processor
#  (available in all templates)
# -------------------------------
@app.context_processor
def inject_author_and_image():
    # Look for any uploaded author/team image in static/uploads
    image_url = None
    for fname in os.listdir(UPLOAD_FOLDER):
        if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
            image_url = url_for("static", filename=f"uploads/{fname}")
            break

    return dict(author=AUTHOR_INFO, author_image_url=image_url)


# -------------------------------
#  Database helpers
# -------------------------------
def get_db():
    return psycopg.connect(DB_URL)


def get_cultivars():
    """Return sorted list of distinct cultivars."""
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT cultivar FROM transcripts ORDER BY cultivar;")
        return [row[0] for row in cur.fetchall()]


# -------------------------------
#  HOME PAGE  (Dashboard)
# -------------------------------
@app.route("/")
def home():
    with get_db() as conn, conn.cursor() as cur:
        # Total transcripts
        cur.execute("SELECT COUNT(*) FROM transcripts;")
        total_transcripts = cur.fetchone()[0] or 0

        # Average length
        cur.execute("SELECT AVG(length) FROM transcripts;")
        avg_length = cur.fetchone()[0] or 0

        # Average GC content
        cur.execute("SELECT AVG(gc_content) FROM transcripts;")
        avg_gc = cur.fetchone()[0] or 0

        # Length range
        cur.execute("SELECT MIN(length), MAX(length) FROM transcripts;")
        min_len, max_len = cur.fetchone()

        # Per-cultivar: count + avg GC
        cur.execute(
            """
            SELECT cultivar, COUNT(*), AVG(gc_content)
            FROM transcripts
            GROUP BY cultivar
            ORDER BY cultivar;
            """
        )
        cultivar_stats = cur.fetchall()
        # cultivar_stats: [(cultivar, count, avg_gc), ...]

    chart_labels = [row[0] for row in cultivar_stats]
    chart_counts = [row[1] for row in cultivar_stats]
    chart_avg_gc = [float(row[2]) if row[2] is not None else 0 for row in cultivar_stats]

    stats = {
        "total_transcripts": total_transcripts,
        "avg_length": avg_length,
        "avg_gc": avg_gc,
        "min_length": min_len,
        "max_length": max_len,
        "cultivar_stats": cultivar_stats,
        "chart": {
            "labels": chart_labels,
            "counts": chart_counts,
            "avg_gc": chart_avg_gc,
        },
    }

    return render_template(
    "home.html",
    stats=stats,
    author=AUTHOR_INFO,
    creator_photo=creator_photo,
    supervisor_photo=supervisor_photo
)


# -------------------------------
#  SEARCH PAGE
# -------------------------------
@app.route("/search", methods=["GET", "POST"])
def search():
    if request.method == "POST":
        # Redirect to GET with query params (clean URL)
        return redirect(
            url_for(
                "search",
                query=request.form.get("query", "").strip(),
                cultivar=request.form.get("cultivar", "").strip(),
                min_gc=request.form.get("min_gc", "").strip(),
                max_gc=request.form.get("max_gc", "").strip(),
                min_len=request.form.get("min_len", "").strip(),
                max_len=request.form.get("max_len", "").strip(),
            )
        )

    # GET params
    query = request.args.get("query", "").strip()
    cultivar = request.args.get("cultivar", "").strip()
    min_gc = request.args.get("min_gc", "").strip()
    max_gc = request.args.get("max_gc", "").strip()
    min_len = request.args.get("min_len", "").strip()
    max_len = request.args.get("max_len", "").strip()
    page = int(request.args.get("page", 1))

    where = []
    params = []

    # Header / "gene" search
    if query:
        where.append("header ILIKE %s")
        params.append(f"%{query}%")

    # Cultivar filter
    if cultivar:
        where.append("cultivar = %s")
        params.append(cultivar)

    # GC content filters
    try:
        if min_gc:
            v = float(min_gc)
            where.append("gc_content >= %s")
            params.append(v)
    except ValueError:
        pass

    try:
        if max_gc:
            v = float(max_gc)
            where.append("gc_content <= %s")
            params.append(v)
    except ValueError:
        pass

    # Length filters
    try:
        if min_len:
            v = int(min_len)
            where.append("length >= %s")
            params.append(v)
    except ValueError:
        pass

    try:
        if max_len:
            v = int(max_len)
            where.append("length <= %s")
            params.append(v)
    except ValueError:
        pass

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    offset = (page - 1) * RESULTS_PER_PAGE

    with get_db() as conn, conn.cursor() as cur:
        # Total count for pagination
        count_sql = f"SELECT COUNT(*) FROM transcripts {where_sql};"
        cur.execute(count_sql, params)
        total_results = cur.fetchone()[0] or 0

        # Actual results
        search_sql = f"""
            SELECT id, header, cultivar, length, gc_content
            FROM transcripts
            {where_sql}
            ORDER BY length DESC
            LIMIT %s OFFSET %s;
        """
        cur.execute(search_sql, params + [RESULTS_PER_PAGE, offset])
        results = cur.fetchall()

    total_pages = max(1, math.ceil(total_results / RESULTS_PER_PAGE))

    cultivar_list = get_cultivars()

    return render_template(
        "search.html",
        results=results,
        page=page,
        total_pages=total_pages,
        total_results=total_results,
        query=query,
        cultivar=cultivar,
        min_gc=min_gc,
        max_gc=max_gc,
        min_len=min_len,
        max_len=max_len,
        cultivars=cultivar_list,
    )


# -------------------------------
#  SINGLE TRANSCRIPT VIEW
# -------------------------------
@app.route("/transcript/<int:tid>")
def transcript_view(tid: int):
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, header, cultivar, length, gc_content, sequence, description
            FROM transcripts
            WHERE id = %s;
            """,
            (tid,),
        )
        row = cur.fetchone()

    if not row:
        abort(404)

    t = {
        "id": row[0],
        "header": row[1],
        "cultivar": row[2],
        "length": row[3],
        "gc_content": row[4],
        "sequence": row[5],
        "description": row[6],
    }

    return render_template("transcript.html", t=t)


# -------------------------------
#  FASTA DOWNLOAD
# -------------------------------
@app.route("/download/<int:tid>.fasta")
def download_fasta(tid: int):
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT header, sequence FROM transcripts WHERE id = %s;", (tid,)
        )
        row = cur.fetchone()

    if not row:
        abort(404)

    header, sequence = row
    safe_name = header.split()[0].replace(" ", "_").replace("/", "_")
    fasta = f">{header}\n{sequence}\n"

    resp = make_response(fasta)
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Content-Disposition"] = f"attachment; filename={safe_name}.fasta"
    return resp


# -------------------------------
#  ABOUT PAGE
# -------------------------------
@app.route("/about")
def about():
    cultivar_list = get_cultivars()
    return render_template("about.html", cultivars=cultivar_list)


# -------------------------------
#  ADMIN: Upload author image
#   (only for creator, via token)
# -------------------------------
@app.route("/admin/upload-author", methods=["GET", "POST"])
def upload_author():
    if request.method == "POST":
        token = request.form.get("token", "").strip()
        if token != ADMIN_TOKEN:
            flash("Invalid admin token. Access denied.", "danger")
            return redirect(url_for("upload_author"))

        file = request.files.get("author_image")
        if not file or file.filename == "":
            flash("No file selected.", "warning")
            return redirect(url_for("upload_author"))

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".gif"]:
            flash("Please upload a PNG/JPG/GIF image.", "warning")
            return redirect(url_for("upload_author"))

        save_name = "team" + ext
        save_path = os.path.join(UPLOAD_FOLDER, save_name)

        # Remove old images
        for fname in os.listdir(UPLOAD_FOLDER):
            if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                os.remove(os.path.join(UPLOAD_FOLDER, fname))

        file.save(save_path)
        flash("Author image updated successfully!", "success")
        return redirect(url_for("home"))

    return render_template("upload.html")


# -------------------------------
#  Run app
# -------------------------------
if __name__ == "__main__":
    # host="0.0.0.0" so you can view from browser on Windows
    app.run(host="0.0.0.0", port=5000, debug=True)
