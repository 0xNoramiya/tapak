"""English for the web UI, keyed by the Indonesian message (``tapak/web/i18n.py``).

A value is the English text, or for a message shown with a count (``ngettext``) the pair
(one, other). Sentences the core library writes (trace notes, registry problems, errors) are
here too when they are fixed; ``RULES`` covers the ones built with values.
``tests/test_bahasa.py`` checks that every message of the pages has an entry.
"""

from __future__ import annotations

import re

EN: dict[str, str | tuple[str, str]] = {
    # ---------------------------------------------------------------- site frame (_situs, _bahasa)
    "Bahasa": "Language",
    "Langsung ke konten": "Skip to content",
    "TAPAK, halaman utama": "TAPAK, home page",
    "Tanda Atribusi Penerima Anti-Kolusi \u00b7 versi %(version)s \u00b7 prototipe Kartika Cyber Hackathon 2026":
        "Collusion-resistant recipient attribution marks \u00b7 version %(version)s \u00b7 Kartika Cyber Hackathon 2026 prototype",
    "Semua dokumen, nama, dan bukti contoh fiktif.": "Every sample document, name and piece of evidence is fictional.",
    "Buka aplikasi": "Open the app",
    "Rahasia": "Secret",

    # ---------------------------------------------------------------- landing page
    "TAPAK \u00b7 Lacak sumber kebocoran dokumen rahasia": "TAPAK \u00b7 Trace the source of a leaked classified document",
    "TAPAK menanam sidik tak kasatmata pada setiap salinan dokumen rahasia dan menunjuk penerimanya saat salinan "
    "itu bocor, dengan peluang salah tuduh yang dihitung. Berjalan sepenuhnya luring.":
        "TAPAK puts an invisible fingerprint in every copy of a classified document and names the recipient when "
        "that copy leaks, with a computed chance of accusing the wrong person. It runs fully offline.",
    "Bagian halaman": "Page sections",
    "Masalah": "The problem",
    "Cara kerja": "How it works",
    "Bukti": "Evidence",
    "Untuk instansi": "For agencies",
    "Coba demo": "Try the demo",
    "Atribusi kebocoran untuk instansi pemerintah": "Leak attribution for government agencies",
    'Dokumen rahasia bocor. <span class="ld-h1-accent">TAPAK tahu salinan siapa.</span>':
        'A secret document leaked. <span class="ld-h1-accent">TAPAK knows whose copy it was.</span>',
    "Setiap penerima mendapat salinan yang tampak sama dengan milik orang lain, tetapi membawa sidik tak kasatmata "
    "miliknya sendiri. Saat salinan itu muncul sebagai foto, tangkapan layar, atau PDF yang diteruskan, TAPAK "
    "menyebut penerimanya beserta peluang bahwa tuduhan itu keliru.":
        "Every recipient gets a copy that looks like everyone else\u2019s but carries an invisible fingerprint of its "
        "own. When that copy turns up as a photo, a screenshot or a forwarded PDF, TAPAK names the recipient and "
        "says how likely it is that the accusation is wrong.",
    "Coba demo 3 menit": "Try the 3-minute demo",
    "Lihat cara kerjanya": "See how it works",
    "Sifat utama": "Key properties",
    "Berjalan di jaringan internal, tanpa layanan awan": "Runs on the internal network, no cloud services",
    "Hasilnya langsung menjadi berita acara PDF": "The result comes out as a forensic report PDF",
    "Contoh: foto bocoran dilacak sampai ke salinan #%(n)s": "Example: a leaked photo traced back to copy #%(n)s",
    "Diteruskan ke grup": "Forwarded to a group",
    "Hasil pelacakan": "Trace result",
    "Teridentifikasi": "Identified",
    "Salinan <b>#%(n)s</b> dari %(total)s": "Copy <b>#%(n)s</b> of %(total)s",
    "Skor": "Score",
    "Ambang": "Threshold",
    "Peluang salah tuduh": "Chance of a false accusation",
    "Contoh nyata: foto sintetis salinan #%(n)s dilacak oleh TAPAK. Semua dokumen dan nama fiktif.":
        "A real run: a synthetic photo of copy #%(n)s traced by TAPAK. All documents and names are fictional.",
    "TAPAK dalam angka": "TAPAK in numbers",
    'tuduhan salah dalam <b class="tnum">%(n)s</b> pelacakan uji tertahan':
        'false accusations in <b class="tnum">%(n)s</b> held-out test traces',
    "1 : 1 juta": "1 in a million",
    "batas peluang salah tuduh, ditetapkan sebelum bukti dinilai":
        "cap on the chance of a false accusation, fixed before the evidence is scored",
    "3 dari 3": "3 of 3",
    "pelaku disebut di setiap simulasi saat tiga penerima menggabungkan salinan mereka (8.000 simulasi)":
        "colluders named in every simulation where three recipients merged their copies (8,000 simulations)",
    "tangkapan layar halaman utuh seburam ini pun masih terlacak":
        "a full-page screenshot this blurry is still traced",
    "Masalahnya": "The problem",
    "Kebocoran hari ini tidak lewat server. Lewat kamera ponsel.":
        "Leaks today don\u2019t go through a server. They go through a phone camera.",
    "Seseorang memotret halaman di mejanya dan mengirimnya ke satu grup. Sejam kemudian foto itu sudah diteruskan "
    "ke mana-mana, dan setiap penerima dokumen bisa saja pelakunya.":
        "Someone photographs a page on their desk and sends it to one group chat. An hour later the photo is "
        "everywhere, and anyone who received the document could be the source.",
    "Log dan pengamanan jaringan tidak melihatnya.": "Logs and network security never see it.",
    "Foto layar atau kertas tidak pernah melewati server, surel, atau sistem DLP instansi.":
        "A photo of a screen or of paper never passes the agency\u2019s servers, email or DLP system.",
    "Watermark nama mudah dihilangkan.": "A name watermark is easy to remove.",
    "Nama penerima di pojok halaman cukup dipotong atau ditutup jari sebelum difoto. Setelah itu semua salinan "
    "kembali sama.":
        "The recipient\u2019s name in the corner is cropped out or covered with a finger before the photo. After that "
        "every copy looks the same again.",
    "Menebak merusak satuan.": "Guessing damages the unit.",
    "Penyelidikan manual memakan waktu berminggu-minggu, dan satu tuduhan keliru merusak karier orang yang tidak "
    "bersalah.":
        "A manual investigation takes weeks, and one wrong accusation can end an innocent person\u2019s career.",
    "Dibanding cara yang biasa dipakai": "Compared with the usual methods",
    "Cara melacak kebocoran dan apa yang dapat dilakukannya": "Ways to trace a leak and what each can do",
    "Pertanyaan": "Question",
    "Watermark nama terlihat": "Visible name watermark",
    "Metadata dan log akses": "Metadata and access logs",
    "Pengamanan jaringan (DLP)": "Network security (DLP)",
    "Masih bekerja bila dokumen difoto?": "Still works when the document is photographed?",
    "Masih bekerja bila namanya dipotong atau ditutup?": "Still works when the name is cropped or covered?",
    "Menunjuk penerima, bukan sekadar perangkat atau akun?": "Names a recipient, not just a device or an account?",
    "Bertahan bila beberapa penerima menggabungkan salinan?": "Holds up when several recipients merge their copies?",
    "Menyebut peluang salah tuduhnya?": "States its chance of a false accusation?",
    "Berjalan tanpa layanan awan?": "Runs without cloud services?",
    "ya": "yes",
    "sebagian": "partly",
    "tidak": "no",
    "sebagian atau bergantung pemasangan": "partly, or depends on the setup",
    "Tiga langkah. Bagi penerima, tidak ada yang berubah.": "Three steps. Nothing changes for the recipients.",
    "Terbitkan": "Issue",
    "Unggah PDF dan daftar penerima. TAPAK membuat satu salinan untuk setiap orang, masing-masing dengan sidik unik. "
    "Di mata manusia semuanya identik.":
        "Upload the PDF and the recipient list. TAPAK makes one copy per person, each with its own fingerprint. To "
        "the eye they are all identical.",
    "20 salinan dalam beberapa detik": "20 copies in a few seconds",
    "Bocor": "Leak",
    "Salinan difoto, ditangkap layarnya, dicetak, atau diteruskan. Sidiknya ikut terbawa, juga pada potongan "
    "sebagian halaman.":
        "A copy is photographed, screenshotted, printed or forwarded. The fingerprint goes with it, even in a crop "
        "of part of a page.",
    "Foto, tangkapan layar, cetakan, PDF, teks": "Photos, screenshots, prints, PDFs, text",
    "Lacak": "Trace",
    "Unggah bukti yang beredar. TAPAK membaca sidik yang tersisa dan menyebut penerimanya, atau menjawab "
    "<q>tidak cukup bukti</q> bila buktinya kurang.":
        "Upload the evidence that is going around. TAPAK reads what is left of the fingerprint and names the "
        "recipient, or answers <q>not enough evidence</q> when there is too little to go on.",
    "Hasil langsung menjadi berita acara PDF": "The result becomes a forensic report PDF",
    "Sidik tak kasatmata": "Invisible fingerprints",
    "Lima lapis sidik. Satu hilang, yang lain tetap bicara.": "Five layers of fingerprint. Lose one, the rest still talk.",
    "Kata yang digeser 0,025 milimeter, pola titik samar di latar, karakter tak terlihat, parafrasa kalimat, dan "
    "alamat kanari. Setiap lapis bertahan pada cara bocor yang berbeda, dan dekoder menggabungkan apa pun yang "
    "tersisa.":
        "Words moved by 0.025 millimetres, a faint dot pattern in the background, invisible characters, reworded "
        "sentences and a canary address. Each layer survives a different kind of leak, and the decoder combines "
        "whatever is left.",
    "Lapis sidik dan cara bocor yang dapat dilaluinya": "Fingerprint layers and the leaks each one survives",
    "Lapis": "Layer",
    "PDF diteruskan": "Forwarded PDF",
    "Tangkapan layar": "Screenshot",
    "Foto": "Photo",
    "Cetakan": "Print",
    "Teks disalin": "Copied text",
    "Diketik ulang": "Retyped",
    "Geser kata dan baris": "Word and line shifts",
    "0,025 mm per kata": "0.025 mm per word",
    "Pola titik latar": "Background dot pattern",
    "titik samar, tak terbaca mata": "faint dots the eye does not read",
    "Karakter tak terlihat": "Invisible characters",
    "ikut tersalin bersama teks": "copied along with the text",
    "Varian kalimat": "Sentence variants",
    "parafrasa yang disetujui manusia": "rewordings a person approved",
    "Kanari DNS": "DNS canary",
    "berbunyi saat dibuka di luar jaringan": "goes off when opened outside the network",
    "bertahan": "survives",
    "sebagian atau bersyarat": "partly, or under conditions",
    "Tiga lapis sidik pada salinan sungguhan, diperbesar: huruf yang bergeser 0,025 mm, pola titik latar yang "
    "diperkuat 40 kali, dan simbol lebar-nol di antara kata":
        "Three fingerprint layers on a real copy, magnified: letters shifted by 0.025 mm, the background dot "
        "pattern amplified 40 times, and zero-width symbols between words",
    "Tiga lapis pada salinan sungguhan, diperbesar. Tanpa pembesaran, salinan tampak persis seperti dokumen "
    "induknya.":
        "Three layers on a real copy, magnified. Without magnification the copy looks exactly like its master.",
    "Diuji ribuan kali. Nol orang tak bersalah tertuduh.": "Tested thousands of times. Zero innocent people accused.",
    "Semua angka di bawah berasal dari uji yang dapat diulang di repositori: dokumen fiktif, bukti sintetis, dan "
    "set uji yang dijalankan sekali setelah aturannya dikunci.":
        "Every number below comes from a test you can rerun from the repository: fictional documents, synthetic "
        "evidence, and test sets run once after the rules were locked.",
    "Seberapa sering TAPAK menyebut penerima yang benar": "How often TAPAK names the right recipient",
    "Bukti yang tidak cukup dijawab <q>tidak cukup bukti</q>. Tidak satu pun menunjuk orang lain.":
        "Evidence that falls short gets <q>not enough evidence</q>. Not one result named someone else.",
    "Uji benchmark: foto dan cetakan sintetis": "Benchmark: synthetic photos and prints",
    "Studi registrasi: bukti sebagian dan buram, set uji tertahan": "Registration study: partial and blurry evidence, held-out set",
    "Studi foto yang dipotong pembocor, set uji tertahan": "Study of photos cropped by the leaker, held-out set",
    "Garis tuduh yang tegas": "A clear accusation line",
    "8.000 simulasi persekongkolan tiga orang, dengan delapan strategi menggabungkan salinan. Skor orang tak "
    "bersalah tidak pernah mendekati garis, dan tidak ada pelaku yang lolos.":
        "8,000 simulations of three people colluding, with eight strategies for merging their copies. No innocent "
        "score came near the line, and no colluder got away.",
    "Seberapa kecil peluang salah tuduh": "How small the chance of a false accusation is",
    "Nama baru disebut bila peluangnya di bawah satu banding sejuta. Pada foto uji, peluangnya biasanya jauh "
    "lebih kecil lagi.":
        "A name is given only when that chance is below one in a million. On the test photos it is usually far "
        "smaller.",
    "Dibuat untuk cara kerja instansi pemerintah": "Built for the way government agencies work",
    "Kementerian dan lembaga, TNI dan Polri, pemerintah daerah, BUMN strategis: di mana pun dokumen "
    "berklasifikasi dibagikan kepada banyak orang.":
        "Ministries and agencies, the armed forces and the police, regional governments, strategic state "
        "enterprises: anywhere classified documents go out to many people.",
    "Data tidak pernah keluar dari instansi": "The data never leaves the agency",
    "Penerbitan, pelacakan, dan registri berjalan di komputer atau server internal. Tanpa layanan awan dan tanpa "
    "telemetri. Satu-satunya lalu lintas dari luar adalah kueri DNS yang diterima pendengar kanari, dan kanari "
    "boleh tidak dipakai.":
        "Issuing, tracing and the registry run on an internal computer or server. No cloud services and no "
        "telemetry. The only traffic from outside is the DNS queries the canary listener receives, and canaries "
        "are optional.",
    "Registri hanya menyimpan hash dan kode, tidak pernah isi dokumen atau gambar bukti.":
        "The registry stores hashes and codes only, never document text or evidence images.",
    "Bukti yang dapat dipertanggungjawabkan": "Evidence that stands up",
    "Setiap putusan memuat skor, ambang, dan batas peluang salah tuduh, lalu ditulis sebagai berita acara PDF "
    "yang siap ditandatangani pemeriksa.":
        "Every verdict carries its score, threshold and false-accusation bound, written up as a forensic report "
        "PDF ready for the examiner\u2019s signature.",
    "Registri yang tidak bisa diubah diam-diam": "A registry that cannot be changed quietly",
    "Catatan penerbitan bersifat tambah-saja, berantai SHA-256, dan bertanda tangan Ed25519. Pihak ketiga dapat "
    "memeriksanya hanya dengan kunci publik.":
        "The issuance record is append-only, SHA-256 chained and Ed25519 signed. A third party can check it with "
        "the public key alone.",
    "Adil sejak awal": "Fair from the start",
    "Ambang tuduhan ditetapkan dan dicatat sebelum bukti dinilai. Bila buktinya kurang, jawabannya <q>tidak cukup "
    "bukti</q>.":
        "The accusation threshold is fixed and recorded before the evidence is scored. When the evidence falls "
        "short, the answer is <q>not enough evidence</q>.",
    "Ringan dipasang": "Light to deploy",
    "Satu laptop atau server biasa, tanpa GPU, tersedia sebagai kontainer Docker. Antarmukanya berbahasa "
    "Indonesia dan Inggris.":
        "One ordinary laptop or server, no GPU, available as a Docker container. The interface is in Indonesian "
        "and English.",
    "Cocok untuk": "Good for",
    "Surat telegram": "Telegrams",
    "Nota dinas": "Official memos",
    "Rencana operasi": "Operation plans",
    "Dokumen pengadaan": "Procurement documents",
    "Bahan rapat terbatas": "Closed-meeting briefs",
    "Naskah soal seleksi": "Selection exam papers",
    "Laporan intelijen": "Intelligence reports",
    "Draf peraturan": "Draft regulations",
    "Penerapan": "Rollout",
    "Mulai dari satu satuan": "Start with one unit",
    "Uji coba": "Pilot",
    "Pasang TAPAK di satu server internal. Terbitkan dokumen nyata kepada daftar penerima nyata, dan latih "
    "pelacakan dengan bukti uji.":
        "Install TAPAK on one internal server. Issue real documents to real recipient lists, and practise tracing "
        "with test evidence.",
    "Pelatihan operator": "Operator training",
    "Operator belajar menerbitkan, melacak, membaca hasil, dan memverifikasi registri. Demo terpandu di aplikasi "
    "menjadi bahan latihannya.":
        "Operators learn to issue, trace, read results and verify the registry. The guided demo in the app is the "
        "training material.",
    "Perluasan bertahap": "Step-by-step expansion",
    "Hubungkan dengan alur tata naskah dinas, tambahkan satuan, simpan log jangkar registri di tempat terpisah, "
    "dan pasang pendengar kanari di jaringan luar.":
        "Connect it to the official correspondence workflow, add units, keep the registry anchor log somewhere "
        "separate, and run the canary listener on an outside network.",
    "Batasan": "Limits",
    "Yang belum bisa dilakukan TAPAK": "What TAPAK cannot do yet",
    "TAPAK menjawab <q>tidak cukup bukti</q> setiap kali buktinya kurang. Halaman ini pun menyebut terus terang di "
    "mana batasnya.":
        "TAPAK answers <q>not enough evidence</q> whenever the evidence falls short. This page is just as plain "
        "about where its limits are.",
    "Semua uji memakai foto, cetakan, dan tangkapan layar sintetis. Kamera, monitor, dan printer sungguhan belum "
    "diuji.":
        "Every test used synthetic photos, prints and screenshots. Real cameras, monitors and printers have not "
        "been tested yet.",
    "Dokumen yang diketik ulang hanya menyisakan sedikit sidik. Dokumen satu sampai dua halaman biasanya berakhir "
    "<q>tidak cukup bukti</q>.":
        "A retyped document keeps little of its fingerprint. One- and two-page documents usually end in "
        "<q>not enough evidence</q>.",
    "Cetakan satu halaman disebut pada %(benar)s dari %(n)s foto uji; dua halaman bersama selalu disebut.":
        "A single printed page was named in %(benar)s of %(n)s test photos; two pages together were always named.",
    "Lawan yang memahami TAPAK dapat merusak sidik sehingga tidak ada nama yang disebut. Batas salah tuduh tetap "
    "berlaku selama kunci rahasia aman.":
        "An adversary who understands TAPAK can damage the fingerprint until no name is given. The "
        "false-accusation bound still holds as long as the secret key is safe.",
    "Kanari hanya berbunyi di penampil yang mengambil konten luar, seperti Adobe Reader dan Word.":
        "A canary only goes off in viewers that fetch outside content, such as Adobe Reader and Word.",
    "Lihat sendiri dalam tiga menit.": "See it for yourself in three minutes.",
    "Demo terpandu memakai dokumen fiktif: terbitkan 20 salinan, bocorkan satu sebagai foto ponsel, lalu lacak "
    "pembocornya.":
        "The guided demo uses a fictional document: issue 20 copies, leak one as a phone photo, then trace the "
        "leaker.",
    "Mulai demo": "Start the demo",

    # landing charts (_grafik.html) and the labels of landing.json
    '<b class="tnum">%(benar)s</b> dari <span class="tnum">%(n)s</span>':
        '<b class="tnum">%(benar)s</b> of <span class="tnum">%(n)s</span>',
    "Skor tuduhan dibagi ambang: orang tak bersalah dan anggota persekongkolan":
        "Accusation score divided by the threshold: innocent recipients and colluders",
    "Skor %(n)s penerima tak bersalah paling tinggi %(pct)s persen dari ambang.":
        "The scores of %(n)s innocent recipients reach at most %(pct)s percent of the threshold.",
    "Skor %(n)s anggota persekongkolan paling rendah %(pct)s persen dari ambang.":
        "The scores of %(n)s colluders are at least %(pct)s percent of the threshold.",
    "Tidak ada skor di antara keduanya.": "No score falls between the two.",
    "celah kosong": "empty gap",
    "ambang tuduhan": "accusation threshold",
    "tak bersalah": "innocent",
    "pelaku": "colluders",
    '%(n)s skor penerima tak bersalah, tertinggi <b class="tnum">%(pct)s%%</b> dari ambang':
        '%(n)s innocent recipients\u2019 scores, highest <b class="tnum">%(pct)s%%</b> of the threshold',
    '%(n)s skor anggota persekongkolan, terendah <b class="tnum">%(pct)s%%</b> dari ambang':
        '%(n)s colluders\u2019 scores, lowest <b class="tnum">%(pct)s%%</b> of the threshold',
    "Batas peluang salah tuduh per jenis bukti, skala logaritmik":
        "Bound on the chance of a false accusation per kind of evidence, log scale",
    "Nama baru disebut bila batasnya di bawah 10 pangkat minus 6.":
        "A name is given only when the bound is below 10 to the power of minus 6.",
    "%(label)s: median 10 pangkat %(median)s, terburuk 10 pangkat %(worst)s.":
        "%(label)s: median 10 to the power of %(median)s, worst 10 to the power of %(worst)s.",
    "syarat menyebut nama": "needed to give a name",
    "makin ke kanan, makin kecil": "further right is smaller",
    "median per jenis bukti": "median per kind of evidence",
    "bukti terlemah yang tetap disebut": "weakest evidence that was still named",
    "Foto layar dan tangkapan layar": "Photos of a screen and screenshots",
    "Foto dengan pemrosesan kamera ponsel": "Photos with phone camera processing",
    "Foto layar monitor": "Photos of a monitor",
    "Cetakan difoto, dua halaman": "Printed and photographed, two pages",
    "Cetakan difoto, satu halaman": "Printed and photographed, one page",
    "Halaman utuh 24 sampai 48 dpi": "Whole pages at 24 to 48 dpi",
    "Potongan tangkapan layar": "Cropped screenshots",
    "Foto ponsel sebagian halaman": "Phone photos of part of a page",
    "Satu paragraf saja": "A single paragraph",
    "Foto ponsel dipotong lalu diperkecil": "Phone photos cropped and then shrunk",
    "Foto layar": "Screen photo",
    "Foto ISP ponsel": "Phone ISP photo",
    "Foto monitor": "Monitor photo",
    "Cetak, 2 halaman": "Print, 2 pages",
    "Cetak, 1 halaman": "Print, 1 page",

    # ---------------------------------------------------------------- demo (demo.html, _demo_alur.html)
    "Demo terpandu \u00b7 TAPAK": "Guided demo \u00b7 TAPAK",
    "Terbitkan nota dinas fiktif kepada 20 penerima, bocorkan satu salinan, lalu lihat TAPAK menemukan "
    "pembocornya.":
        "Issue a fictional memo to 20 recipients, leak one copy, and watch TAPAK find the leaker.",
    "Demo terpandu": "Guided demo",
    "Halaman produk": "Product page",
    "Dokumen dan nama fiktif": "Fictional document and names",
    "Temukan pembocornya dalam empat langkah": "Find the leaker in four steps",
    "Anda membagikan nota dinas rahasia kepada 20 orang, dan salah satunya membocorkan salinannya. Anda yang "
    "memilih siapa dan bagaimana. TAPAK hanya melihat barang buktinya.":
        "You share a secret memo with 20 people, and one of them leaks their copy. You pick who and how. TAPAK "
        "only gets to see the evidence.",
    "Demo berjalan di ruang kerja terpisah dengan kunci dan registrinya sendiri. Dokumen, kunci, dan registri "
    "Anda tidak tersentuh, dan tidak ada data yang dikirim ke luar komputer ini.":
        "The demo runs in a separate workspace with its own keys and registry. Your documents, keys and registry "
        "are not touched, and no data leaves this computer.",
    "Setelah demo": "After the demo",
    "Memakai TAPAK untuk dokumen nyata": "Using TAPAK on real documents",
    "Alurnya sama dengan demo ini, dengan dokumen dan daftar penerima Anda sendiri.":
        "It is the same flow as this demo, with your own document and recipient list.",
    "Terbitkan dokumen": "Issue a document",
    "Siapkan dua berkas.": "Prepare two files.",
    'PDF induk dokumen (berlapis teks atau hasil pindai) dan daftar penerima dalam CSV dengan kolom '
    '<span class="mono">recipient_id, nama, jabatan, satuan</span>.':
        'The master PDF (with a text layer, or scanned) and the recipient list as a CSV with the columns '
        '<span class="mono">recipient_id, nama, jabatan, satuan</span> (id, name, position, unit).',
    "Unduh contoh CSV": "Download a sample CSV",
    "Terbitkan.": "Issue.",
    'Di halaman <a class="link" href="/terbitkan">Terbitkan</a>, unggah keduanya, tinjau varian kalimat yang '
    'diusulkan, lalu unduh ZIP berisi satu salinan per penerima.':
        'On the <a class="link" href="/terbitkan">Issue</a> page, upload both, review the proposed sentence '
        'variants, then download a ZIP with one copy per recipient.',
    "Bagikan.": "Share.",
    "Kirim setiap salinan hanya kepada penerimanya. Registri mencatat salinan mana untuk siapa, tanpa menyimpan "
    "isi dokumen.":
        "Send each copy to its recipient only. The registry records which copy went to whom, without storing the "
        "document\u2019s contents.",
    "Bila bocor, lacak.": "If it leaks, trace it.",
    'Di halaman <a class="link" href="/lacak">Lacak</a>, pilih dokumennya dan unggah apa pun yang beredar: foto, '
    'tangkapan layar, PDF, DOCX, atau teks yang ditempel.':
        'On the <a class="link" href="/lacak">Trace</a> page, choose the document and upload whatever is going '
        'around: a photo, a screenshot, a PDF, a DOCX, or pasted text.',
    "Laporkan.": "Report.",
    'Unduh berita acara PDF dari hasil pelacakan, dan periksa keutuhan catatan penerbitan di halaman '
    '<a class="link" href="/registri">Registri</a>.':
        'Download the forensic report PDF from the trace result, and check that the issuance record is intact on '
        'the <a class="link" href="/registri">Registry</a> page.',
    "Bocorkan": "Leak",
    "Hasil": "Result",
    "%(num)s salinan": ("%(num)s copy", "%(num)s copies"),
    "nota dinas fiktif": "a fictional memo",
    "Anda pilih pembocornya": "you pick the leaker",
    "%(s)s detik": "%(s)s seconds",
    "dari barang bukti saja": "from the evidence alone",
    "Tidak cukup bukti": "Not enough evidence",
    "putusan dan berita acara": "verdict and report",
    "Langkah demo": "Demo steps",
    "Langkah %(n)s:": "Step %(n)s:",
    "selesai": "done",
    "Langkah %(n)s dari 4": "Step %(n)s of 4",
    "Terbitkan 20 salinan": "Issue 20 copies",
    "Nota dinas contoh (2 halaman, fiktif) diterbitkan untuk 20 penerima fiktif. TAPAK membuat satu salinan untuk "
    "setiap orang dan menanam sidiknya di lima lapis:":
        "The sample memo (2 pages, fictional) goes to 20 fictional recipients. TAPAK makes one copy per person and "
        "puts its fingerprint in five layers:",
    "geser kata dan baris": "word and line shifts",
    "pola titik latar": "background dot pattern",
    "karakter tak terlihat": "invisible characters",
    "varian kalimat": "sentence variants",
    "alamat kanari": "a canary address",
    "Menerbitkan 20 salinan\u2026": "Issuing 20 copies\u2026",
    "Butuh beberapa detik, dan semuanya dikerjakan di komputer ini.": "It takes a few seconds, all on this computer.",
    "Halaman 1 nota dinas contoh": "Page 1 of the sample memo",
    "dokumen induk": "master document",
    "Bocorkan satu salinan": "Leak one copy",
    "%(n)s salinan terbit dalam %(s)s detik, masing-masing tercatat di registri demo.":
        "%(n)s copies issued in %(s)s seconds, each recorded in the demo registry.",
    "%(n)s salinan sudah terbit, masing-masing tercatat di registri demo.":
        "%(n)s copies are issued, each recorded in the demo registry.",
    "Semuanya tampak sama. Pilih siapa yang membocorkan salinannya dan bagaimana caranya.":
        "They all look the same. Pick who leaks their copy, and how.",
    "Terbitkan ulang? Salinan, bukti, dan registri demo yang lama dihapus.":
        "Issue again? The old demo copies, evidence and registry are deleted.",
    "Menerbitkan ulang\u2026": "Issuing again\u2026",
    "Terbitkan ulang": "Issue again",
    "Halaman 1 salinan #%(n)s": "Page 1 of copy #%(n)s",
    "Salinan #%(n)s": "Copy #%(n)s",
    "Selisih salinan #1 dan #2 pada separuh atas halaman 1, diperkuat 40 kali: titik-titik pola latar dan tepi "
    "kata yang bergeser":
        "Difference between copies #1 and #2 on the top half of page 1, amplified 40 times: the background dots "
        "and the edges of shifted words",
    "Selisih keduanya, diperkuat 40 kali: titik pola latar dan tepi kata yang bergeser, berbeda untuk setiap "
    "penerima.":
        "Their difference, amplified 40 times: background dots and the edges of shifted words, different for every "
        "recipient.",
    "Siapa pembocornya?": "Who is the leaker?",
    "Pelacak tidak diberi tahu pilihan Anda.": "The tracer is not told your choice.",
    "Bagaimana salinan itu bocor?": "How does the copy leak?",
    "Bocorkan salinan": "Leak the copy",
    "Membuat barang bukti\u2026": "Making the evidence\u2026",
    "Barang bukti yang beredar: %(cara)s dari salinan yang dibocorkan":
        "The evidence going around: %(cara)s of the leaked copy",
    "Lacak sumbernya": "Trace the source",
    "Salinan #%(n)s bocor: %(cara)s. Mulai dari sini TAPAK hanya melihat berkas ini, seperti penyidik yang "
    "menemukannya di grup percakapan.":
        "Copy #%(n)s leaked: %(cara)s. From here on TAPAK sees only this file, like an investigator who found it in "
        "a group chat.",
    "TAPAK membaca sidik yang tersisa, menggabungkan semua lapis, lalu membandingkan skor setiap salinan dengan "
    "ambang yang ditetapkan sebelum skor dihitung.":
        "TAPAK reads what is left of the fingerprint, combines every layer, then compares each copy\u2019s score with a "
        "threshold fixed before any score is computed.",
    "Lacak barang bukti ini": "Trace this evidence",
    "Menganalisis bukti, 10 sampai 40 detik\u2026": "Analysing the evidence, 10 to 40 seconds\u2026",
    "Unduh berkas bukti": "Download the evidence file",
    "Ganti pembocor atau cara bocor": "Change the leaker or the leak",
    "<b>Tepat.</b> Ini salinan yang Anda bocorkan di langkah 2, ditemukan dalam %(s)s detik. Tidak ada penerima "
    "lain yang disebut.":
        "<b>Correct.</b> This is the copy you leaked in step 2, found in %(s)s seconds. No other recipient was named.",
    "TAPAK menyebut salinan #%(named)s, sedangkan yang dibocorkan salinan #%(n)s. Ini tidak boleh terjadi; simpan "
    "berkas buktinya dan laporkan.":
        "TAPAK named copy #%(named)s, but the leaked copy was #%(n)s. This must not happen; keep the evidence file "
        "and report it.",
    "TAPAK tidak menyebut nama": "TAPAK names no one",
    "Sidik yang tersisa di barang bukti ini (%(cara)s) tidak cukup kuat untuk menyebut nama dengan peluang salah "
    "tuduh di bawah batasnya, jadi TAPAK tidak menebak.":
        "What is left of the fingerprint in this evidence (%(cara)s) is not strong enough to give a name with the "
        "chance of a false accusation under its bound, so TAPAK does not guess.",
    "Teks yang disalin hanya membawa karakter tak terlihat dan varian kalimat; bila aplikasi pesan membuang "
    "karakter tak terlihat, yang tersisa terlalu sedikit.":
        "Copied text carries only the invisible characters and the sentence variants; when a messaging app strips "
        "the invisible characters, too little is left.",
    "Coba cara bocor lain.": "Try another kind of leak.",
    "Perhatian:": "Note:",
    "Skor setiap salinan": "Every copy\u2019s score",
    "Skor salinan #%(n)s %(skor)s, ambang %(z)s, skor tertinggi penerima lain %(lain)s.":
        "Copy #%(n)s scored %(skor)s, the threshold is %(z)s, and the highest score of any other recipient is %(lain)s.",
    "Skor tertinggi %(skor)s, di bawah ambang %(z)s.": "The highest score is %(skor)s, below the threshold of %(z)s.",
    "ambang": "threshold",
    "penerima lain, tanpa nomor": "other recipients, unnumbered",
    "salinan yang disebut": "the named copy",
    "ambang, ditetapkan sebelum skor dihitung": "threshold, fixed before any score is computed",
    "Skor salinan #%(n)s": "Score of copy #%(n)s",
    "%(k)s kali ambang": "%(k)s times the threshold",
    "Skor tertinggi penerima lain": "Highest score of another recipient",
    "Peluang menunjuk orang yang salah": "Chance of naming the wrong person",
    "paling besar %(p)s": "at most %(p)s",
    "Berita acara": "Forensic report",
    "SHA-256 barang bukti, dokumen induk, parameter kode, skor, ambang, dan batas peluang salah tuduh, siap "
    "ditandatangani pemeriksa. Formulirnya berbahasa Indonesia.":
        "The evidence\u2019s SHA-256, the master document, the code parameters, the score, the threshold and the "
        "false-accusation bound, ready for the examiner\u2019s signature. The form itself is in Indonesian.",
    "Unduh berita acara PDF": "Download the report PDF",
    "Coba pembocor atau cara bocor lain": "Try another leaker or leak",
    "Pakai dokumen sendiri": "Use your own document",
    "Pilih penerima yang membocorkan salinannya.": "Pick the recipient who leaks their copy.",
    "Pilih cara salinan itu bocor.": "Pick how the copy leaks.",
    "Hasil pelacakan tidak ditemukan; jalankan pelacakan lagi": "Trace result not found; run the trace again",
    "Salinan demo tidak ditemukan": "Demo copy not found",
    "Bukti demo tidak ditemukan; buat bukti baru di langkah 2": "Demo evidence not found; make new evidence in step 2",
    "penerbitan demo lain sedang berjalan; coba lagi sebentar lagi":
        "another demo issuance is running; try again in a moment",
    "Terbitkan salinan demo lebih dulu (langkah 1).": "Issue the demo copies first (step 1).",
    "Bukti demo tidak ditemukan. Buat bukti baru di langkah 2.": "Demo evidence not found. Make new evidence in step 2.",
    "Berita acara tidak dapat dibuat: %(reason)s": "The forensic report could not be made: %(reason)s",
    "Demo tidak dapat diterbitkan: %(reason)s": "The demo could not be issued: %(reason)s",
    "Pelacakan tidak dapat dilakukan: %(reason)s": "The trace could not be run: %(reason)s",
    "Difoto dengan ponsel": "Photographed with a phone",
    "Halaman 1 difoto miring dengan bayangan dan sedikit buram, lalu dikirim lewat aplikasi pesan.":
        "Page 1 photographed at an angle, with a shadow and a little blur, then sent through a messaging app.",
    "Halaman 1 dibuka di penampil PDF, ditangkap layarnya, lalu dikompresi aplikasi pesan.":
        "Page 1 opened in a PDF viewer, screenshotted, then compressed by a messaging app.",
    "Salinan ditampilkan di monitor, lalu layarnya difoto dengan ponsel.":
        "The copy shown on a monitor, and the screen photographed with a phone.",
    "Potongan halaman": "Part of a page",
    "Hanya bagian tengah halaman 1 yang ditangkap layarnya.": "Only the middle of page 1 is screenshotted.",
    "Berkas salinan dikirim apa adanya.": "The copy\u2019s file is sent as it is.",
    # spoken forms of powers of ten (a screen reader does not announce a superscript)
    "%(m)s kali 10 pangkat %(minus)s%(e)s": "%(m)s times 10 to the power of %(minus)s%(e)s",
    "10 pangkat %(minus)s%(e)s": "10 to the power of %(minus)s%(e)s",
    "minus ": "minus ",
    "Isi dokumen disalin dari PDF dan ditempel ke percakapan.":
        "The document\u2019s text copied out of the PDF and pasted into a chat.",

    # ---------------------------------------------------------------- app shell (base.html, scripts)
    "Klasifikasi": "Classification",
    "RAHASIA": "SECRET",
    "TAPAK, beranda": "TAPAK, home",
    'Tanda Atribusi Penerima <span class="nowrap">Anti-Kolusi</span>':
        'Collusion-resistant <span class="nowrap">recipient attribution</span>',
    "Menu utama": "Main menu",
    "Beranda": "Home",
    "Demo": "Demo",
    "Registri": "Registry",
    "Tidak ada data yang dikirim keluar dari perangkat ini": "No data is sent off this device",
    "<b>Luring</b>, semua diproses di perangkat ini": "<b>Offline</b>, everything runs on this device",
    "Halaman produk TAPAK": "TAPAK product page",
    "TAPAK %(version)s \u00b7 prototipe Kartika Cyber Hackathon 2026 \u00b7 data contoh sepenuhnya fiktif":
        "TAPAK %(version)s \u00b7 Kartika Cyber Hackathon 2026 prototype \u00b7 all sample data is fictional",
    "Registri:": "Registry:",
    "Permintaan ditolak server (kode %%(kode)s). Periksa isian lalu coba lagi.":
        "The server refused the request (code %%(kode)s). Check the form and try again.",
    "Server TAPAK tidak dapat dihubungi. Periksa apakah layanan berjalan, lalu coba lagi.":
        "The TAPAK server cannot be reached. Check that the service is running, then try again.",
    "Pilih satu berkas.": "Choose one file.",
    "Tersalin": "Copied",
    "Disalin ke papan klip.": "Copied to the clipboard.",
    "Gagal menyalin. Pilih teksnya lalu salin manual.": "Copy failed. Select the text and copy it by hand.",
    "Salin": "Copy",
    "Galat": "Error",
    "Tidak ditemukan": "Not found",
    "Kesalahan di server": "Server error",
    "Permintaan tidak dapat dipenuhi": "The request cannot be completed",
    "Ke beranda": "Go home",
    "Mulai lagi": "Start over",
    "Buka Lacak": "Open Trace",

    # ---------------------------------------------------------------- home (beranda.html)
    "Atribusi kebocoran dokumen": "Document leak attribution",
    "Setiap salinan membawa tanda penerimanya": "Every copy carries its recipient\u2019s mark",
    "Bila dokumen bocor, TAPAK menunjuk salinan sumbernya beserta peluang tuduhan salahnya.":
        "When a document leaks, TAPAK points to the copy it came from and gives the chance that the accusation is wrong.",
    "Lacak kebocoran": "Trace a leak",
    "Belum ada dokumen yang diterbitkan.": "No document has been issued yet.",
    "Unggah PDF induk dan daftar penerima. TAPAK membuat satu salinan bertanda untuk setiap penerima dan mencatatnya di registri.":
        "Upload the master PDF and the recipient list. TAPAK makes one marked copy per recipient and records it in the registry.",
    "Terbitkan dokumen pertama": "Issue the first document",
    "Ringkasan": "Summary",
    "Dokumen terbit": "Documents issued",
    "tercatat di registri": "recorded in the registry",
    "belum terverifikasi": "not verified yet",
    "Salinan": "Copies",
    "masing-masing bertanda unik": "each with its own mark",
    "%(n)s entri": "%(n)s entries",
    "%(n)s belum bertanda tangan": "%(n)s unsigned",
    "lihat penyebabnya": "see why",
    "Kueri kanari": "Canary queries",
    "dari %(num)s salinan": ("from %(num)s copy", "from %(num)s copies"),
    "belum ada yang terdeteksi": "none detected yet",
    "Dokumen terbaru": "Latest documents",
    "Semua %(n)s dokumen": "All %(n)s documents",
    "Unduh ZIP salinan %(doc)s": "Download the ZIP of copies of %(doc)s",
    "Lacak kebocoran %(doc)s": "Trace a leak of %(doc)s",
    "Kueri kanari terbaru": "Latest canary queries",
    "Salinan yang terdeteksi dibuka di luar jaringan satuan.": "Copies detected being opened outside the unit\u2019s network.",
    "kueri %(jenis)s": "%(jenis)s query",
    "Semua %(n)s kueri": "All %(n)s queries",
    "Belum ada kueri.": "No queries yet.",

    # ---------------------------------------------------------------- issue (terbitkan.html and its steps)
    "Penandaan luring \u00b7 kode Tardos": "Offline marking \u00b7 Tardos code",
    "Terbitkan salinan bertanda": "Issue marked copies",
    "Setiap penerima mendapat salinan dengan sidiknya sendiri. Jika salinan bocor, TAPAK dapat menunjuk salinan sumbernya beserta peluang tuduhan salahnya.":
        "Every recipient gets a copy with its own fingerprint. If a copy leaks, TAPAK can point to the copy it came from and give the chance that the accusation is wrong.",
    "Langkah penerbitan": "Issuing steps",
    "Dokumen": "Document",
    "Rencana": "Plan",
    "Tinjau teks": "Review text",
    "tidak berlaku": "not applicable",
    "Dokumen dan penerima": "Document and recipients",
    "Dokumen induk tetap di perangkat ini. Registri hanya menyimpan hash dokumen dan komitmen kode setiap penerima.":
        "The master document stays on this device. The registry stores only the document\u2019s hash and each recipient\u2019s code commitment.",
    "Pilih berkas": "Choose a file",
    "Dokumen induk (PDF)": "Master document (PDF)",
    'Seret ke sini atau <span class="dropzone-link">pilih berkas</span>. PDF berlapis teks atau hasil pindai (minimal 200&nbsp;dpi), maks. 40&nbsp;MB.':
        'Drag it here or <span class="dropzone-link">choose a file</span>. A PDF with a text layer, or scanned (at least 200&nbsp;dpi), up to 40&nbsp;MB.',
    "Daftar penerima (CSV)": "Recipient list (CSV)",
    'Seret ke sini atau <span class="dropzone-link">pilih berkas</span>. Kolom wajib <span class="mono">recipient_id</span> dan <span class="mono">nama</span>; <span class="mono">jabatan</span> dan <span class="mono">satuan</span> opsional.':
        'Drag it here or <span class="dropzone-link">choose a file</span>. Required columns <span class="mono">recipient_id</span> and <span class="mono">nama</span> (name); <span class="mono">jabatan</span> (position) and <span class="mono">satuan</span> (unit) are optional.',
    'Penerbit <span class="field-optional">(opsional)</span>': 'Issuer <span class="field-optional">(optional)</span>',
    "contoh: Kasi Ops Brigif 9905": "for example: Kasi Ops Brigif 9905",
    "Tercatat di registri sebagai pihak yang menerbitkan.": "Recorded in the registry as the issuing party.",
    "Pola latar": "Background pattern",
    "Lapisan kode di bawah teks halaman. Pilih menurut cara salinan akan dibagikan.":
        "A layer of code under the page text. Choose by how the copies will be shared.",
    'Layar <span class="field-optional">(bawaan)</span>': 'Screen <span class="field-optional">(default)</span>',
    "Tidak terlihat, tetapi hilang bila salinan dicetak.": "Invisible, but lost when a copy is printed.",
    "Cetak": "Print",
    "Bertahan di kertas dalam uji printer simulasi, tetapi halaman tampak abu-abu muda.":
        "Survives on paper in the simulated printer tests, but the page looks light grey.",
    "Skema geser kata": "Word shift scheme",
    "Geser kata dan baris yang tetap terbaca pada foto kertas cetak.":
        "Word and line shifts that can still be read in a photo of a printed page.",
    "(bawaan)": "(default)",
    "Kelompok kata kontrol dan data berselang-seling, geser 0,05 mm.":
        "Control and data word groups alternate, 0.05 mm shifts.",
    "Setiap kelompok kata membawa bit, geser 0,025 mm: lebih banyak posisi pada foto kertas cetak yang tajam.":
        "Every word group carries a bit, 0.025 mm shifts: more positions in a sharp photo of a printed page.",
    "Parameter kode dan kanari": "Code and canary settings",
    "Ukuran koalisi yang ditahan (c)": "Coalition size resisted (c)",
    "Jumlah penerima yang mungkin bersekongkol membandingkan salinan.": "How many recipients might collude by comparing copies.",
    "Peluang tuduhan salah maksimum": "Maximum chance of a false accusation",
    "Untuk seluruh daftar penerima, ditetapkan sebelum analisis apa pun.": "For the whole recipient list, fixed before any analysis.",
    "Domain kanari": "Canary domain",
    "Kosongkan untuk menonaktifkan token kanari.": "Leave empty to turn canary tokens off.",
    "Analisis dokumen": "Analyse the document",
    "Menganalisis dokumen\u2026": "Analysing the document\u2026",
    "Membaca lapisan teks dan menguji gerbang visual. Untuk PDF hasil pindai: %(scan)s":
        "Reading the text layer and testing the visual gate. For a scanned PDF: %(scan)s",
    '<a class="link" href="%(href)s">Lacak kebocorannya</a> atau unggah dokumen lain.':
        '<a class="link" href="%(href)s">Trace its leak</a> or upload another document.',
    "Rencana penandaan": "Marking plan",
    '<span class="mono">%(doc)s</span> untuk %(n)s penerima. Kode setiap penerima disebar ke beberapa kanal; tiap kanal bertahan terhadap perubahan yang berbeda.':
        '<span class="mono">%(doc)s</span> for %(n)s recipients. Each recipient\u2019s code is spread over several channels; each channel survives different changes.',
    "Halaman 1 %(doc)s": "Page 1 of %(doc)s",
    "Gerbang visual": "Visual gate",
    "Lulus": "Passed",
    "Gagal": "Failed",
    'Tanpa tanda, halaman teks digambar ulang identik dengan aslinya: selisih maksimum %(n)s tingkat <span class="nowrap">abu-abu.</span>':
        'Without marks, the text pages redraw identical to the original: largest difference %(n)s grey <span class="nowrap">levels.</span>',
    'Tanpa tanda, dokumen digambar ulang identik dengan aslinya: selisih maksimum %(n)s tingkat <span class="nowrap">abu-abu.</span>':
        'Without marks, the document redraws identical to the original: largest difference %(n)s grey <span class="nowrap">levels.</span>',
    "Halaman": "Pages",
    "%(n)s halaman teks,": "%(n)s text pages,",
    "%(n)s halaman pindaian (%(dpi)s&nbsp;dpi)": "%(n)s scanned pages (%(dpi)s&nbsp;dpi)",
    "dan": "and",
    "%(n)s kata,": "%(n)s words,",
    "%(n)s kotak kata (Tesseract)": "%(n)s word boxes (Tesseract)",
    "%(n)s kata": "%(n)s words",
    "Panjang kode": "Code length",
    "bit Tardos per penerima": "Tardos bits per recipient",
    "Tahan kolusi": "Resists collusion",
    "penerima bersekongkol": "colluding recipients",
    "Ambang penuh": "Full threshold",
    "skor minimum untuk menuduh": "lowest score that accuses",
    "Kapasitas kanal penandaan": "Capacity of the marking channels",
    "Kanal": "Channel",
    "Slot": "Slots",
    "Cakupan kode": "Code coverage",
    "cetak, foto, tangkapan layar": "print, photo, screenshot",
    "cetak dalam uji printer simulasi, layar, tangkapan layar, foto layar":
        "print in the simulated printer tests, screen, screenshot, photo of a screen",
    "layar, tangkapan layar, foto layar": "screen, screenshot, photo of a screen",
    "salin-tempel, berkas diteruskan": "copy and paste, forwarded file",
    "salin-tempel, teks dinormalkan sebagian": "copy and paste, partly normalised text",
    "; di halaman pindaian: digeser di piksel gambar": "; on scanned pages: shifted in the image pixels",
    "; di halaman pindaian: ditambahkan ke piksel kertas": "; on scanned pages: added to the paper pixels",
    " (halaman teks saja)": " (text pages only)",
    "profil %(p)s": "%(p)s profile",
    "layar": "screen",
    "cetak": "print",
    "skema %(s)s": "scheme %(s)s",
    "Bertahan: %(cara)s": "Survives: %(cara)s",
    "Token kanari": "Canary token",
    'Mendeteksi berkas dibuka di luar jaringan satuan (DNS ke <span class="mono">%(domain)s</span>)':
        'Detects the file being opened outside the unit\u2019s network (DNS to <span class="mono">%(domain)s</span>)',
    "tidak membawa kode": "carries no code",
    "Bilah menunjukkan bagian dari %(n)s posisi kode yang dibawa kanal itu. Bilah penuh berarti kanal itu sendiri dapat membawa seluruh kode.":
        "The bar shows the share of the %(n)s code positions that channel carries. A full bar means the channel alone can carry the whole code.",
    "Mode halaman": "Page modes",
    "Halaman %(n)s: pindaian, %(dpi)s dpi": "Page %(n)s: scanned, %(dpi)s dpi",
    "Halaman %(n)s: teks": "Page %(n)s: text",
    "Halaman %(n)s: tanpa teks, tidak ada kata untuk ditandai": "Page %(n)s: no text, no word to mark",
    "Pelacakan membaca ulang kotak kata ini dengan Tesseract. Bila hasilnya berbeda dari saat penerbitan (misalnya karena versi Tesseract lain), kanal geser halaman pindaian dilewati dan hanya pola latarnya yang dibaca. Simpan versi Tesseract ini bersama instalasi TAPAK.":
        "A trace reads these word boxes again with Tesseract. If the result differs from issuance (for example with another Tesseract version), the shift channel of the scanned pages is skipped and only their background pattern is read. Keep this Tesseract version with the TAPAK installation.",
    "Ukuran: gambar halaman salinan disimpan tanpa kompresi yang menurunkan mutu, jadi salinan bisa jauh lebih besar dari induk hasil pindai JPEG (contoh 300&nbsp;dpi: sekitar 2,9&nbsp;MB per halaman salinan, induk 0,7&nbsp;MB per halaman). Ukuran sebenarnya ditampilkan setelah terbit.":
        "Size: the copies\u2019 page images are stored without lossy compression, so a copy can be much larger than a JPEG-scanned master (example at 300&nbsp;dpi: about 2.9&nbsp;MB per copy page, master 0.7&nbsp;MB per page). The real sizes are shown after issuing.",
    "Waktu: %(n)s salinan &times; %(pages)s halaman pindaian ditandai di piksel gambar, jadi penerbitan lebih lama dari dokumen teks (contoh: 20 salinan &times; 2 halaman 300&nbsp;dpi sekitar 30 detik). Melacak satu PDF salinan 2 halaman memerlukan sekitar 40 detik.":
        "Time: %(n)s copies &times; %(pages)s scanned pages are marked in the image pixels, so issuing takes longer than for a text document (example: 20 copies &times; 2 pages at 300&nbsp;dpi take about 30 seconds). Tracing one 2-page copy PDF takes about 40 seconds.",
    "Halaman pindaian: gambar halaman salinan tanpa tanda identik piksel demi piksel dengan gambar induk, dan render halamannya berselisih paling banyak %(n)s tingkat abu-abu dari halaman induk.":
        "Scanned pages: the unmarked copy\u2019s page image matches the master image pixel for pixel, and its rendered page differs from the master page by at most %(n)s grey levels.",
    "Halaman pindaian: gambar halaman salinan tanpa tanda tidak identik dengan gambar induk, atau render halamannya melewati batas gerbang visual; penerbitan ditolak.":
        "Scanned pages: the unmarked copy\u2019s page image does not match the master image, or its rendered page goes past the visual gate\u2019s limit; issuing refused.",
    "Membaca kotak kata halaman pindaian dengan Tesseract (beberapa detik per halaman).":
        "Reading the word boxes of the scanned pages with Tesseract (a few seconds per page).",
    "Tidak berlaku: semua halaman dokumen ini hasil pindai": "Not applicable: every page of this document is scanned",
    "Kalimat aman dan pilihan kata hanya dapat ditanam di lapisan teks, jadi keduanya dilewati dan tidak ada yang perlu ditinjau.":
        "Safe sentences and word choice can only be put in a text layer, so both are skipped and there is nothing to review.",
    "Salinan tetap membawa kanal geser dan pola latar di piksel gambar halaman. Teks yang diketik ulang dari salinan tidak membawa tanda, sehingga pengetikan ulang dokumen ini tidak dapat dilacak.":
        "The copies still carry the shift channel and the background pattern in the page image pixels. Text retyped from a copy carries no mark, so a retyped version of this document cannot be traced.",
    'Kalimat aman <span class="field-optional">(opsional)</span>': 'Safe sentences <span class="field-optional">(optional)</span>',
    "Kalimat pembuka, penutup, dan tembusan dapat diparafrasekan per penerima oleh LLM lokal. Bersama pilihan kata (di bawah), hanya kanal ini yang bertahan bila dokumen diketik ulang. Perintah, angka, nama, waktu, dan koordinat tidak pernah ditawarkan.":
        "Opening, closing and copy-to sentences can be reworded per recipient by a local LLM. Together with word choice (below), this is the only channel that survives retyping. Orders, numbers, names, times and coordinates are never offered.",
    "Buat ulang varian? Keputusan untuk varian yang teksnya tetap sama dipertahankan; varian baru harus ditinjau lagi.":
        "Make the variants again? Decisions on variants whose text stays the same are kept; new variants must be reviewed again.",
    "Pilih kalimat yang diparafrasekan": "Choose the sentences to reword",
    "Halaman %(n)s": "Page %(n)s",
    "Tidak ada kalimat yang aman untuk diparafrasekan. Kanal varian kalimat tidak dipakai.":
        "No sentence is safe to reword. The sentence-variant channel is not used.",
    "%(num)s kalimat tidak ditawarkan": ("%(num)s sentence not offered", "%(num)s sentences not offered"),
    "Alasan: %(why)s.": "Reason: %(why)s.",
    "Buat ulang varian": "Make the variants again",
    "Buat varian dengan LLM lokal": "Make variants with the local LLM",
    "Membuat varian\u2026": "Making variants\u2026",
    "LLM lokal memparafrasekan kalimat terpilih. Dengan model sungguhan di CPU, ini dapat memakan beberapa menit.":
        "The local LLM is rewording the chosen sentences. With a real model on a CPU this can take a few minutes.",
    "Tidak ada kalimat pembuka, penutup, atau tembusan yang dikenali di dokumen ini. Kanal varian kalimat tidak dipakai.":
        "No opening, closing or copy-to sentence was recognised in this document. The sentence-variant channel is not used.",
    "%(n)s dari %(total)s varian menunggu tinjauan Anda.": "%(n)s of %(total)s variants await your review.",
    "Semua varian sudah ditinjau.": "Every variant has been reviewed.",
    "Tinjau varian": "Review the variants",
    "%(n)s titik pilihan kata masih menunggu.": "%(n)s word-choice points still wait.",
    "Asli, halaman %(n)s": "Original, page %(n)s",
    "Pemeriksa kesetaraan, semua varian": "Equivalence checker, all variants",
    "Varian dari model bahasa ditinjau satu per satu.": "Variants from a language model are reviewed one by one.",
    "Setujui semua (%(n)s)": "Approve all (%(n)s)",
    "Semua sudah ditinjau": "All reviewed",
    "Disetujui": "Approved",
    "Ditolak": "Rejected",
    "Menunggu": "Waiting",
    "Pemeriksa kesetaraan": "Equivalence checker",
    "Putusan varian %(i)s kalimat halaman %(page)s": "Decision on variant %(i)s of the sentence on page %(page)s",
    "Setujui varian %(i)s kalimat halaman %(page)s": "Approve variant %(i)s of the sentence on page %(page)s",
    "Setujui": "Approve",
    "Tolak varian %(i)s kalimat halaman %(page)s": "Reject variant %(i)s of the sentence on page %(page)s",
    "Tolak": "Reject",
    "Tidak ada varian yang lolos pemeriksaan otomatis untuk kalimat ini.": "No variant of this sentence passed the automatic checks.",
    "%(num)s usulan ditolak otomatis": ("%(num)s proposal rejected automatically", "%(num)s proposals rejected automatically"),
    "Penerbitan diblokir sampai setiap varian dan titik pilihan kata disetujui atau ditolak (%(n)s varian dan %(lex)s titik menunggu).":
        "Issuing is blocked until every variant and word-choice point is approved or rejected (%(n)s variants and %(lex)s points waiting).",
    "Penerbitan diblokir sampai setiap varian disetujui atau ditolak (%(n)s menunggu).":
        "Issuing is blocked until every variant is approved or rejected (%(n)s waiting).",
    "Penerbitan diblokir sampai setiap titik pilihan kata disetujui atau ditolak (%(n)s menunggu).":
        "Issuing is blocked until every word-choice point is approved or rejected (%(n)s waiting).",
    "Salinan dibuat dan dicatat di registri yang ditandatangani. Kode setiap penerima tidak disimpan, hanya komitmennya.":
        "The copies are made and recorded in the signed registry. No recipient\u2019s code is stored, only its commitment.",
    "Terbitkan %(n)s salinan": "Issue %(n)s copies",
    "Menerbitkan\u2026": "Issuing\u2026",
    "Menandai dan merender %(n)s salinan.": "Marking and rendering %(n)s copies.",
    "Halaman pindaian ditandai di piksel gambar, jadi lebih lama (contoh: 20 salinan dokumen 2 halaman pindaian 300&nbsp;dpi sekitar 30 detik).":
        "Scanned pages are marked in the image pixels, so this takes longer (example: 20 copies of a 2-page scan at 300&nbsp;dpi take about 30 seconds).",
    "Tahan ketik ulang": "Survives retyping",
    "bit.": "bits.",
    "Teks yang diketik ulang dari salinan tidak membawa tanda.": "Text retyped from a copy carries no mark.",
    "bit: %(lex)s&nbsp;bit pilihan kata + %(sem)s&nbsp;bit varian kalimat":
        "bits: %(lex)s&nbsp;word-choice bits + %(sem)s&nbsp;sentence-variant bits",
    "Hanya varian kalimat dan pilihan kata, keduanya opsional, bertahan bila teks diketik ulang.":
        "Only sentence variants and word choice, both optional, survive retyping.",
    "Halaman pindaian tidak membawa keduanya.": "Scanned pages carry neither.",

    # word choice (_leksikal.html)
    "Kanal pilihan kata tidak dipakai.": "The word-choice channel is not used.",
    "%(num)s frasa ditolak pemeriksaan otomatis": ("%(num)s phrase rejected by the automatic checks", "%(num)s phrases rejected by the automatic checks"),
    "Frasa ditolak per kategori": "Phrases rejected, by category",
    "frasa": "phrases",
    "Penolakan hanya disebut per kategori, tanpa kata dokumen.": "Rejections are given by category only, without any word of the document.",
    "Tidak ada frasa yang ditolak pemeriksaan otomatis.": "The automatic checks rejected no phrase.",
    "Hal.": "Page",
    "Salinan contoh 1": "Sample copy 1",
    "Salinan contoh 2": "Sample copy 2",
    "Salinan 1": "Copy 1",
    "Salinan 2": "Copy 2",
    "sama di kedua salinan": "the same in both copies",
    'Pilihan kata <span class="field-optional">(opsional)</span>': 'Word choice <span class="field-optional">(optional)</span>',
    "Setiap penerima mendapat bentuk kata sendiri yang bermakna sama, misalnya \u201cterdiri atas\u201d atau \u201cterdiri dari\u201d, sehingga teks yang diketik ulang tetap dapat dilacak. Akibatnya salinan terlihat berbeda kata bila dibandingkan; dokumen induk tetap menjadi catatan resmi.":
        "Every recipient gets their own form of words with the same meaning, for example \u201cterdiri atas\u201d or \u201cterdiri dari\u201d, so retyped text can still be traced. As a result the copies show different words when compared; the master document stays the official record.",
    "Hanya halaman teks. Halaman pindaian (halaman %(nums)s) tidak membawa kanal ini.":
        "Text pages only. The scanned pages (pages %(nums)s) do not carry this channel.",
    "Jangan pakai pilihan kata? %(n)s keputusan titik akan dihapus.": "Stop using word choice? %(n)s point decisions will be deleted.",
    "Jangan pakai pilihan kata": "Do not use word choice",
    "<b>Leksikon %(title)s versi %(version)s: DRAF, belum disahkan peninjau bahasa Tata Naskah Dinas.</b> Pemeriksaan otomatis hanya menyaring; setiap titik tetap Anda tinjau.":
        "<b>Lexicon %(title)s version %(version)s: DRAFT, not yet approved by an official-correspondence language reviewer.</b> The automatic checks only filter; you still review every point.",
    "Tabel leksikon tidak dapat dipakai: %(why)s": "The lexicon table cannot be used: %(why)s",
    "Teks ketikan ulang baru cukup untuk menyebut satu pembocor mulai %(bits)s&nbsp;bit, sekitar %(words)s&nbsp;kata isi dengan tabel ini. Dokumen yang lebih pendek tetap berakhir \u201ctidak cukup bukti\u201d. Tanpa pemindaian, salinan diterbitkan tanpa kanal ini.":
        "Retyped text is enough to name a single leaker from %(bits)s&nbsp;bits, about %(words)s&nbsp;content words with this table. Shorter documents still end in \u201cnot enough evidence\u201d. Without a scan, the copies are issued without this channel.",
    "Pindai titik pilihan kata": "Scan for word-choice points",
    "Memindai\u2026": "Scanning\u2026",
    "Mencari frasa dari tabel leksikon di badan dokumen.": "Looking for phrases from the lexicon table in the document body.",
    "Tidak ada frasa di dokumen ini yang lolos pemeriksaan dan muat pada barisnya. Salinan diterbitkan tanpa kanal pilihan kata.":
        "No phrase in this document passed the checks and fits its line. The copies are issued without the word-choice channel.",
    "%(n)s&nbsp;kata isi diperiksa.": "%(n)s&nbsp;content words checked.",
    "Tinjau titik": "Review the points",
    "%(n)s dari %(total)s titik menunggu tinjauan Anda.": "%(n)s of %(total)s points await your review.",
    "Semua titik sudah ditinjau.": "Every point has been reviewed.",
    "Lompat ke Terbitkan": "Skip to Issue",
    "%(n)s titik dari %(words)s&nbsp;kata isi. Baca setiap kalimat. Setujui hanya bila setiap bentuknya tetap baku dan maknanya sama persis di kalimat itu.":
        "%(n)s points from %(words)s&nbsp;content words. Read every sentence. Approve only when every form stays standard and means exactly the same in that sentence.",
    "%(n)s menunggu": "%(n)s waiting",
    "Semua ditinjau": "All reviewed",
    "Contoh:": "Example:",
    "Semua titik \u201c%(forms)s\u201d": "Every \u201c%(forms)s\u201d point",
    "Setujui %(n)s titik \u201c%(forms)s\u201d sekaligus? Lakukan ini hanya setelah setiap kalimatnya Anda baca.":
        "Approve %(n)s \u201c%(forms)s\u201d points at once? Do this only after reading every sentence.",
    "Setujui yang menunggu (%(n)s)": "Approve the waiting ones (%(n)s)",
    "Tidak ada yang menunggu": "None waiting",
    "Tolak semua (%(n)s)": "Reject all (%(n)s)",
    "Semua ditolak": "All rejected",
    "titik %(no)s (\u201c%(form)s\u201d), halaman %(page)s": "point %(no)s (\u201c%(form)s\u201d), page %(page)s",
    "Konteks berulang: frasa dan kata di sekitarnya juga ada di bagian lain dokumen. Tolak bila bocoran dapat menukar urutan kalimat.":
        "Repeated context: the phrase and the words around it also appear elsewhere in the document. Reject it if a leak could swap the order of sentences.",
    "Titik %(no)s \u00b7 halaman %(page)s \u00b7 %(num)s&nbsp;bit": ("Point %(no)s \u00b7 page %(page)s \u00b7 %(num)s&nbsp;bit",
                                                          "Point %(no)s \u00b7 page %(page)s \u00b7 %(num)s&nbsp;bits"),
    "bit": ("bit", "bits"),
    "bentuk:": "forms:",
    "Putusan %(name)s": "Decision on %(name)s",
    "Setujui %(name)s": "Approve %(name)s",
    "Tolak %(name)s": "Reject %(name)s",
    "Satu pembocor": "One leaker",
    "Bila semua titik yang menunggu disetujui: %(n)s&nbsp;bit pilihan kata.": "If every waiting point is approved: %(n)s&nbsp;word-choice bits.",
    "Tidak ada titik yang disetujui: salinan diterbitkan tanpa kanal pilihan kata.": "No point approved: the copies are issued without the word-choice channel.",
    "Nama yang hanya didukung teks ketikan ulang selalu diberi peringatan tanda terlihat: siapa pun yang pernah membaca salinan itu dapat meniru pilihan katanya, jadi nama itu memerlukan bukti pendukung.":
        "A name backed only by retyped text always carries a visible-marks warning: anyone who has read that copy can imitate its word choices, so the name needs supporting evidence.",
    "Contoh dua salinan": "Two sample copies",
    "Dua salinan contoh yang paling berbeda, dari delapan: berbeda pada %(n)s dari %(total)s titik yang disetujui.":
        "The two most different sample copies out of eight: they differ on %(n)s of %(total)s approved points.",
    "Baris yang memuat titik yang disetujui, seperti tercetak. Bentuk yang berbeda diberi latar; bentuk yang sama digarisbawahi titik-titik.":
        "Lines with approved points, as printed. Differing forms are shaded; matching forms have a dotted underline.",
    "Delapan salinan contoh memakai bentuk yang sama pada %(n)s titik yang disetujui; salinan penerima tetap dapat berbeda.":
        "Eight sample copies use the same forms on %(n)s approved points; recipients\u2019 copies can still differ.",
    "Baris yang berbeda pada kedua salinan contoh": "Lines that differ between the two sample copies",
    "%(num)s baris sama di kedua contoh": ("%(num)s line the same in both samples", "%(num)s lines the same in both samples"),
    "Baris yang sama pada kedua salinan contoh": "Lines that are the same in both sample copies",
    "Baris pada kedua salinan contoh": "Lines of both sample copies",
    "Baris-baris ini digambar ulang kata demi kata, jadi keluar dari kanal geser (%(lost)s&nbsp;dari %(all)s&nbsp;bit geser). Tabel rencana di atas menunjukkan angka sebelum pilihan kata.":
        "These lines are redrawn word by word, so they leave the shift channel (%(lost)s&nbsp;of %(all)s&nbsp;shift bits). The plan table above shows the numbers before word choice.",
    "Setujui titik untuk melihat bagaimana dua salinan berbeda.": "Approve points to see how two copies differ.",

    # issued (_hasil_terbit.html)
    "Tercatat": "Recorded",
    "Registri %(n)s entri, ditandatangani": "Registry %(n)s entries, signed",
    "Belum bertanda tangan": "Not signed yet",
    "Registri %(n)s entri, menunggu tanda tangan eselon atas": "Registry %(n)s entries, awaiting the higher echelon\u2019s signature",
    "%(n)s salinan siap dibagikan": "%(n)s copies ready to share",
    '<span class="mono">%(doc)s</span>, diterbitkan %(when)s oleh %(who)s dalam %(s)s detik.':
        '<span class="mono">%(doc)s</span>, issued %(when)s by %(who)s in %(s)s seconds.',
    "Unduh semua salinan (ZIP)": "Download every copy (ZIP)",
    "Lacak dokumen ini": "Trace this document",
    "Terbitkan dokumen lain": "Issue another document",
    "Cukup untuk satu pembocor": "Enough for one leaker",
    "Belum cukup": "Not enough yet",
    "%(lex)s&nbsp;bit pilihan kata + %(sem)s&nbsp;bit varian kalimat": "%(lex)s&nbsp;word-choice bits + %(sem)s&nbsp;sentence-variant bits",
    'Pilihan kata disimpan sebagai <span class="mono">leksikal.json</span> di samping dokumen induk; registri hanya mencatat digest-nya.':
        'The word choices are stored as <span class="mono">leksikal.json</span> next to the master document; the registry records only its digest.',
    "Halaman pindaian": "Scanned pages",
    "Ukuran salinan: rata-rata %(mean)s&nbsp;MB, terbesar %(max)s&nbsp;MB (dokumen induk %(master)s&nbsp;MB). Gambar halaman pindaian disimpan tanpa kompresi yang menurunkan mutu.":
        "Copy sizes: %(mean)s&nbsp;MB on average, %(max)s&nbsp;MB at most (master document %(master)s&nbsp;MB). Scanned page images are stored without lossy compression.",
    "Daftar salinan": "Copies",
    "Bagikan setiap salinan hanya kepada penerimanya. Komitmen kode tercatat di registri; kodenya sendiri tidak disimpan.":
        "Share each copy with its recipient only. The code commitment is in the registry; the code itself is not stored.",
    "No.": "No.",
    "Penerima": "Recipient",
    "Satuan": "Unit",
    "Kalimat diubah": "Sentences changed",
    "Komitmen kode": "Code commitment",
    "Unduh": "Download",
    "%(n)s dari %(total)s": "%(n)s of %(total)s",
    "Unduh salinan %(n)s, %(who)s": "Download copy %(n)s, %(who)s",

    # ---------------------------------------------------------------- trace (lacak.html, _lacak_form, _hasil_lacak)
    "Dekoder luring \u00b7 ambang Chernoff": "Offline decoder \u00b7 Chernoff threshold",
    "Lacak sumber kebocoran": "Trace the source of a leak",
    "Unggah apa pun yang bocor: foto layar atau kertas, tangkapan layar, PDF atau DOCX yang diteruskan, atau teks yang disalin.":
        "Upload whatever leaked: a photo of a screen or of paper, a screenshot, a forwarded PDF or DOCX, or copied text.",
    "<b>Menganalisis bukti.</b> Foto memerlukan beberapa detik untuk diluruskan dan dibaca.":
        "<b>Analysing the evidence.</b> A photo takes a few seconds to straighten and read.",
    "Dokumen ini memuat halaman pindaian: kotak katanya dibaca ulang dengan Tesseract dan halaman itu pada bukti dibaca sebagai gambar, jadi lebih lama (contoh: satu PDF salinan 2 halaman sekitar 40 detik).":
        "This document has scanned pages: their word boxes are read again with Tesseract and those pages of the evidence are read as images, so it takes longer (example: one 2-page copy PDF takes about 40 seconds).",
    "Ambang Z": "Threshold Z",
    "Belum ada hasil pelacakan.": "No trace result yet.",
    "Skor tiap salinan dibandingkan dengan ambang Z, yang ditetapkan sebelum skor siapa pun dihitung. Nama hanya disebut bila skornya melewati ambang itu.":
        "Each copy\u2019s score is compared with the threshold Z, which is fixed before anyone\u2019s score is computed. A name is given only when its score passes that threshold.",
    "Kebocoran hanya dapat dilacak pada dokumen yang diterbitkan lewat TAPAK.": "Only documents issued through TAPAK can be traced.",
    "Dokumen yang diduga bocor": "The document suspected of leaking",
    "pukul %(jam)s": "at %(jam)s",
    "Halaman 1 dokumen yang dipilih": "Page 1 of the chosen document",
    "Pratinjau tidak tersedia untuk DOCX": "No preview for DOCX",
    "Bukti yang bocor": "Leaked evidence",
    "Foto, tangkapan layar, PDF, DOCX, atau TXT": "Photo, screenshot, PDF, DOCX or TXT",
    'Seret ke sini atau <span class="dropzone-link">pilih berkas</span>.': 'Drag it here or <span class="dropzone-link">choose a file</span>.',
    "Foto tiap halaman dari kebocoran yang sama boleh dipilih sekaligus; buktinya digabung.":
        "Photos of each page from the same leak can be chosen together; the evidence is combined.",
    "Atau tempel teks yang bocor": "Or paste the leaked text",
    "diabaikan karena ada berkas": "ignored because a file is chosen",
    "Teks yang bocor": "Leaked text",
    "Tempel teks dari pesan atau dokumen di sini": "Paste text from a message or a document here",
    "Dipakai bila tidak ada berkas yang dipilih. Ctrl+Enter untuk melacak.": "Used when no file is chosen. Ctrl+Enter to trace.",
    "Lacak sumber": "Trace the source",
    "Menganalisis bukti\u2026": "Analysing the evidence\u2026",
    "tak hingga": "infinite",
    "Peluang tuduhan salah": "Chance of a false accusation",
    "Hasil atribusi": "Attribution result",
    "Kanal sepakat": "Channels agreeing",
    ", masing-masing secara independen": ", each independently",
    "Pelacakan bertahap": "Staged trace",
    "Tahap lanjutan hanya berjalan karena tahap 1 menuduh salinan di atas. Tahap itu memakai ambang dan jatah peluang tuduhan salahnya sendiri, dan skornya memakai bobot tahap itu, sehingga tidak dapat dibandingkan langsung dengan skor tahap 1.":
        "The later stage only ran because stage 1 accused the copy above. It uses its own threshold and its own share of the false-accusation chance, and its scores use that stage\u2019s weights, so they cannot be compared directly with stage 1 scores.",
    "Tahap %(n)s": "Stage %(n)s",
    "Skor tahap %(n)s": "Stage %(n)s score",
    "Ambang Z%(n)s": "Threshold Z%(n)s",
    "Lebih dari satu salinan dituduh, di tahap 1 dan di tahap lanjutan: pola ini sesuai dengan kolusi (bukti disusun dari beberapa salinan).":
        "More than one copy was accused, in stage 1 and in a later stage: this pattern fits collusion (evidence put together from several copies).",
    "Lebih dari satu salinan melewati ambang: pola ini sesuai dengan kolusi (bukti disusun dari beberapa salinan).":
        "More than one copy passed the threshold: this pattern fits collusion (evidence put together from several copies).",
    "Tidak ada salinan yang mencapai ambang Z. Nama tidak disebutkan.": "No copy reached the threshold Z. No name is given.",
    "Skor tertinggi": "Highest score",
    "Posisi kode yang terbaca terlalu sedikit: tidak ada skor yang dapat mencapai ambang Z. Nama tidak disebutkan.":
        "Too few code positions were read: no score could reach the threshold Z. No name is given.",
    "Tidak ada tanda yang terbaca pada bukti ini. Nama tidak disebutkan.": "No mark could be read in this evidence. No name is given.",
    '<a class="link" href="#sah-h">Angka setiap pemeriksaan</a> ada di Keabsahan dan catatan.':
        '<a class="link" href="#sah-h">The numbers of each check</a> are under Validity and notes.',
    "Unduh berita acara (PDF)": "Download the forensic report (PDF)",
    "Foto halaman lain dari kebocoran yang sama dapat diunggah bersama; buktinya digabung.":
        "Photos of other pages from the same leak can be uploaded together; the evidence is combined.",
    "Rincian teknis untuk pemeriksa": "Technical details for the examiner",
    "Bukti per kanal": "Evidence per channel",
    "Ambang Z = %(z)s ditetapkan %(when)s dari %(n)s posisi kode yang terbaca, sebelum skor siapa pun dihitung. Ini pelacakan ke-%(no)s atas dokumen ini dan sudah dicatat di registri sebelum dekode. Pelacakan ini memakai %(share)s&nbsp;%% dari batas peluang tuduhan salah %(eps)s, sehingga semua pelacakan dokumen ini bersama tetap dalam batas itu untuk seluruh daftar penerima.":
        "Threshold Z = %(z)s was fixed %(when)s from %(n)s code positions read, before anyone\u2019s score was computed. This is trace number %(no)s of this document, recorded in the registry before decoding. It uses %(share)s&nbsp;%% of the %(eps)s false-accusation bound, so all traces of this document together stay within that bound for the whole recipient list.",
    "Ambang Z = %(z)s ditetapkan %(when)s dari %(n)s posisi kode yang terbaca, sebelum skor siapa pun dihitung (peluang tuduhan salah maksimum %(eps)s untuk seluruh daftar penerima).":
        "Threshold Z = %(z)s was fixed %(when)s from %(n)s code positions read, before anyone\u2019s score was computed (largest chance of a false accusation %(eps)s for the whole recipient list).",
    "Tidak ada posisi kode yang terbaca pada bukti ini, sehingga tidak ada ambang maupun skor yang berlaku.":
        "No code position could be read in this evidence, so there is no threshold and no score.",
    "Posisi terbaca": "Positions read",
    "Ambang kanal": "Channel threshold",
    "Menunjuk salinan": "Points to copy",
    "%(num)s salinan lain (nomor tidak dicantumkan)": ("%(num)s other copy (number not shown)", "%(num)s other copies (numbers not shown)"),
    "tidak ada": "none",
    "Tidak ada kanal yang terbaca.": "No channel could be read.",
    "Bilah menunjukkan bagian dari %(n)s posisi kode yang terbaca lewat kanal itu.": "The bar shows the share of the %(n)s code positions read through that channel.",
    "tahap 1 memakai %(share)s&nbsp;%% dari batas peluang tuduhan salah %(eps)s": "stage 1 uses %(share)s&nbsp;%% of the %(eps)s false-accusation bound",
    "%(share)s&nbsp;%% dari jatah pelacakan ini": "%(share)s&nbsp;%% of this trace\u2019s share",
    "Kebijakan %(policy)s: %(stage1)s. Tahap lanjutan membagi sisanya; ambang setiap tahap ditetapkan sebelum skor tahap itu dihitung.":
        "Policy %(policy)s: %(stage1)s. The later stages split the rest; each stage\u2019s threshold is fixed before that stage\u2019s scores are computed.",
    "Tahap": "Stage",
    'Posisi<span class="tahap-th-sisa"> tak terjelaskan</span>': 'Positions<span class="tahap-th-sisa"> unexplained</span>',
    "Ambang tahap": "Stage threshold",
    "Jatah": "Share",
    "Menuduh": "Accuses",
    "dasar": "basis",
    "Tahap lanjutan hanya menimbang posisi tak terjelaskan, yaitu posisi yang bit bocornya tidak dimiliki salinan dasar. Bobotnya memakai kode salinan yang sudah dituduh, tidak pernah kode salinan yang sedang dinilai. Jatah adalah bagian dari jatah pelacakan ini.":
        "A later stage weighs only unexplained positions, the positions whose leaked bit the basis copies do not have. Its weights use the codes of copies already accused, never the code of the copy being scored. The share is part of this trace\u2019s share.",
    "Pelacakan bertahap: %(stage1)s; tahap lanjutan tidak menuduh salinan lain.": "Staged trace: %(stage1)s; the later stages accused no other copy.",
    "Pelacakan bertahap: %(stage1)s; tahap lanjutan hanya berjalan bila tahap 1 menuduh seseorang.": "Staged trace: %(stage1)s; the later stages run only when stage 1 accuses someone.",
    "Rincian sub-kanal": "Sub-channel details",
    "Sub-kanal": "Sub-channel",
    "Observasi": "Observations",
    "Keterangan": "Details",
    "Peringkat skor": "Score ranking",
    "Skor tahap 1.": "Stage 1 scores.",
    "Garis tegak menandai ambang Z.": "The vertical line marks the threshold Z.",
    "Nomor salinan dan nama hanya ditampilkan untuk salinan yang dituduh: di tahap 1, atau di tahap lanjutan bersama salinan dasarnya, skor tahap, dan ambang tahapnya. Salinan lain disebut dengan peringkatnya saja.":
        "Copy numbers and names are shown only for accused copies: in stage 1, or in a later stage together with its basis copies, stage score and stage threshold. Other copies are given by rank only.",
    "Nomor salinan dan nama hanya ditampilkan untuk salinan yang melewati ambang; salinan lain disebut dengan peringkatnya saja.":
        "Copy numbers and names are shown only for copies past the threshold; other copies are given by rank only.",
    "Melewati ambang": "Past the threshold",
    "di bawah ambang tahap 1,": "below the stage 1 threshold,",
    "%(basis)s; skor tahap %(score)s, ambang Z%(stage)s %(z)s": "%(basis)s; stage score %(score)s, threshold Z%(stage)s %(z)s",
    "Disembunyikan": "Hidden",
    "di bawah ambang": "below the threshold",
    "skor tahap 1": "stage 1 score",
    "skor": "score",
    "Kueri DNS kanari": "Canary DNS queries",
    "%(n)s kueri": "%(n)s queries",
    "Salinan lain": "Another copy",
    "Nama unik salinan itu dicari resolver DNS di luar jaringan satuan, biasanya karena berkasnya dibuka. Alamat yang tercatat adalah resolver, belum tentu komputer pembuka. Ini bukti pendukung, terpisah dari skor; nomor salinan hanya dicantumkan untuk salinan yang juga dituduh hasil atribusi.":
        "A DNS resolver outside the unit\u2019s network looked up that copy\u2019s unique name, usually because the file was opened. The address recorded is the resolver\u2019s, not necessarily the computer that opened it. This is supporting evidence, separate from the score; copy numbers are shown only for copies the attribution also accuses.",
    "Penerima yang juga dituduh": "Recipients also accused",
    "Keabsahan dan catatan": "Validity and notes",
    "Utuh, belum bertanda tangan": "Intact, not signed yet",
    "Utuh": "Intact",
    "Rusak": "Broken",
    "Tidak tercatat": "Not recorded",
    "Tanpa kunci": "No key",
    "Entri": "Entries",
    "%(n)s salinan belum bertanda tangan": "%(n)s copies not signed yet",
    "Komitmen": "Commitments",
    "%(n)s dari %(total)s salinan cocok": "%(n)s of %(total)s copies match",
    "Pola tanda terbalik": "Reversed-mark pattern",
    "Terdeteksi": "Detected",
    "Pola penghapusan": "Erasure pattern",
    "Bacaan jelas tanpa nama": "Clear reading, no name",
    "Pelacakan": "Trace",
    "Ke-%(no)s, entri #%(entry)s, bertanda tangan": "Number %(no)s, entry #%(entry)s, signed",
    "Ke-%(no)s, entri #%(entry)s, belum bertanda tangan": "Number %(no)s, entry #%(entry)s, not signed yet",
    "Log jangkar": "Anchor log",
    "Jangkar pelacakan, catat di luar sistem": "Trace anchor, write it down outside the system",
    "Salin perintah jangkar pelacakan": "Copy the trace anchor command",
    "SHA-256 bukti": "Evidence SHA-256",
    "Salin SHA-256 bukti": "Copy the evidence SHA-256",
    "Catatan": "Notes",

    # ---------------------------------------------------------------- registry (registri.html, _merkle, _status_registri)
    "Rantai hash \u00b7 Ed25519": "Hash chain \u00b7 Ed25519",
    "Registri penerbitan": "Issuance registry",
    "Setiap dokumen dan salinan yang diterbitkan, juga setiap pelacakan, tercatat di sini, tambah-saja. Pemegang berkas registri dan kunci publik dapat memeriksa rantainya tanpa TAPAK.":
        "Every document and copy issued, and every trace, is recorded here, append-only. Anyone holding the registry file and the public key can check its chain without TAPAK.",
    "Tak terbaca": "Unreadable",
    "Kunci publik tidak dapat dibaca": "The public key cannot be read",
    "Rantai registri belum dapat diverifikasi. Ganti berkasnya dengan registry_signing.pub dari pemegang kunci tanda tangan.":
        "The registry chain cannot be verified yet. Replace the file with registry_signing.pub from the signing key holder.",
    "Belum diperiksa": "Not checked",
    "Rantai registri belum dapat diverifikasi": "The registry chain cannot be verified yet",
    "Kunci publik tidak ditemukan, padahal registri sudah berisi %(n)s entri.": "The public key was not found, though the registry already holds %(n)s entries.",
    "Kunci publik tidak ditemukan.": "The public key was not found.",
    "Salin registry_signing.pub dari pemegang kunci tanda tangan ke lokasi di bawah.": "Copy registry_signing.pub from the signing key holder to the location below.",
    "Berkas kunci publik": "Public key file",
    "Rantai registri dimulai saat dokumen pertama diterbitkan.": "The registry chain starts when the first document is issued.",
    "Setiap salinan yang dibuat akan dicatat, di-hash ke entri sebelumnya, dan ditandatangani.": "Every copy made will be recorded, hashed to the entry before it, and signed.",
    "Rantai registri rusak": "The registry chain is broken",
    "Rantai hash utuh, sebagian belum bertanda tangan": "The hash chain is intact, part of it not signed yet",
    "Rantai registri utuh": "The registry chain is intact",
    "Ditemukan %(n)s masalah. Hasil pelacakan dari registri ini tidak dapat dijadikan bukti sampai penyebabnya jelas.":
        "%(n)s problems found. Trace results from this registry cannot serve as evidence until the cause is clear.",
    "%(n)s dari %(total)s entri belum ditandatangani, sehingga belum terlindungi dari pemalsuan.":
        "%(n)s of %(total)s entries are not signed yet, so they are not yet protected against forgery.",
    "Hash dan tanda tangan ke-%(n)s entri sah.": "The hashes and signatures of all %(n)s entries are valid.",
    "Diperiksa saat halaman ini dibuka.": "Checked when this page was opened.",
    "%(docs)s dokumen, %(copies)s salinan": "%(docs)s documents, %(copies)s copies",
    "%(n)s pelacakan": "%(n)s traces",
    "Belum ditandatangani": "Not signed yet",
    "menunggu eselon atas": "awaiting the higher echelon",
    "semua entri ditandatangani": "every entry signed",
    "Entri terakhir": "Last entry",
    'log jangkar: rinciannya di bagian <a class="link" href="#jangkar-h">Log jangkar</a> di bawah':
        'anchor log: details in the <a class="link" href="#jangkar-h">Anchor log</a> section below',
    "Nomor dan hash setiap entri, ditambahkan ke berkas di penyimpanan terpisah. Entri yang dihapus dari ujung registri hanya terlihat dengan log ini, atau dengan jangkar yang tercetak di berita acara.":
        "The number and hash of every entry, appended to a file on separate storage. Entries deleted from the end of the registry show up only with this log, or with the anchor printed in a forensic report.",
    "Belum dimulai": "Not started",
    "Hilang": "Missing",
    "Terlalu besar": "Too large",
    "Tidak terbaca": "Unreadable",
    "Tidak dapat ditulis": "Not writable",
    "Periksa lokasi": "Check the location",
    "Tidak cocok": "Does not match",
    "Tidak diatur": "Not set",
    "Cocok": "Matches",
    "Lokasi": "Location",
    "Dijangkarkan": "Anchored",
    "Sampai entri #%(n)s": "Up to entry #%(n)s",
    "Belum ada entri": "No entries yet",
    "%(n)s entri terakhir dicatat pada penulisan berikutnya": "the last %(n)s entries are written on the next write",
    "Baris": "Lines",
    "%(n)s, %(signed)s bertanda tangan": "%(n)s, %(signed)s signed",
    "Segmen": "Segment",
    "Lanjutan log %(log)s sejak entri #%(n)s, %(when)s": "Continues log %(log)s from entry #%(n)s, %(when)s",
    "Dimulai ulang": "Restarted",
    "Di entri #%(n)s, %(when)s; penghapusan sebelum itu tidak terlihat oleh log ini": "At entry #%(n)s, %(when)s; deletions before that are invisible to this log",
    "Pengakuan": "Acknowledgements",
    "%(acks)s pengakuan pemulihan, %(released)s entri dilepas": "%(acks)s recovery acknowledgements, %(released)s entries released",
    'Pelacakan dan penerbitan ditolak sampai log ini diteruskan ke segmen baru dengan <span class="mono nowrap">tapak jangkar rotasi BERKAS_BARU</span>. Jangan menghapus atau memotong log ini.':
        'Tracing and issuing are refused until this log continues in a new segment with <span class="mono nowrap">tapak jangkar rotasi BERKAS_BARU</span>. Do not delete or truncate this log.',
    'Pelacakan dan penerbitan ditolak sampai log dimulai dengan <span class="mono nowrap">tapak jangkar mulai</span>.':
        'Tracing and issuing are refused until the log is started with <span class="mono nowrap">tapak jangkar mulai</span>.',
    "Pelacakan dan penerbitan ditolak sampai log ini dapat dibaca lagi di lokasinya.": "Tracing and issuing are refused until this log can be read again at its location.",
    "Pelacakan dan penerbitan ditolak sampai lokasi atau penyimpanan log ini diperbaiki.": "Tracing and issuing are refused until this log\u2019s location or storage is fixed.",
    'Pelacakan dan penerbitan ditolak sampai perbedaan ini diperiksa dengan <span class="mono nowrap">tapak verify</span>.':
        'Tracing and issuing are refused until this difference is checked with <span class="mono nowrap">tapak verify</span>.',
    'Registri ini memakai log jangkar sejak entri #%(n)s, tetapi lokasinya tidak diatur di server ini, jadi pelacakan dan penerbitan ditolak. Jalankan server dengan <span class="mono nowrap">tapak --log-jangkar BERKAS web</span> atau atur TAPAK_ANCHOR_LOG.':
        'This registry has used an anchor log since entry #%(n)s, but its location is not set on this server, so tracing and issuing are refused. Run the server with <span class="mono nowrap">tapak --log-jangkar BERKAS web</span> or set TAPAK_ANCHOR_LOG.',
    'Belum dipakai. Pilih berkas di penyimpanan yang tidak dapat disunting orang yang dapat menyunting registri, jalankan <span class="mono nowrap">tapak --log-jangkar BERKAS jangkar mulai</span>, lalu jalankan server dengan lokasi yang sama.':
        'Not in use. Choose a file on storage that the people who can edit the registry cannot edit, run <span class="mono nowrap">tapak --log-jangkar BERKAS jangkar mulai</span>, then run the server with the same location.',
    "Kunci publik": "Public key",
    "Serahkan bersama berkas registri kepada pemeriksa. Keduanya cukup untuk memverifikasi rantai di luar TAPAK.":
        "Hand it to the examiner with the registry file. The two are enough to verify the chain outside TAPAK.",
    "Isi berkasnya bukan kunci publik Ed25519 yang sah, jadi tidak ditampilkan.": "The file does not hold a valid Ed25519 public key, so it is not shown.",
    "Ed25519, heksadesimal": "Ed25519, hexadecimal",
    "Salin kunci publik": "Copy the public key",
    "Perintah verifikasi mandiri": "Independent verification command",
    "Salin perintah verifikasi": "Copy the verification command",
    'Belum ada di server ini. Jangan membuat kunci baru dengan <span class="mono nowrap">tapak keys init</span>: tanda tangan entri yang ada tidak akan cocok dengannya.':
        'Not on this server yet. Do not make a new key with <span class="mono nowrap">tapak keys init</span>: the signatures of the existing entries would not match it.',
    'Kunci belum dibuat. Jalankan <span class="mono nowrap">tapak keys init</span> di server ini.':
        'No key yet. Run <span class="mono nowrap">tapak keys init</span> on this server.',
    "Akar Merkle harian": "Daily Merkle roots",
    "Satu akar mengikat semua entri sehari. Kirim berkasnya ke eselon atas sebagai jangkar: entri lama yang diubah tidak akan cocok lagi.":
        "One root binds all of a day\u2019s entries. Send the file to the higher echelon as an anchor: an old entry that was changed will no longer match.",
    "Mengekspor\u2026": "Exporting\u2026",
    "Ekspor akar Merkle harian": "Export the daily Merkle roots",
    "Setiap salinan membawa nama domain unik. Bila resolver di luar jaringan satuan mencarinya, berkas itu kemungkinan dibuka di sana.":
        "Every copy carries a unique domain name. When a resolver outside the unit\u2019s network looks it up, the file was probably opened there.",
    "Log rusak": "Log broken",
    "Rantai hash %(n)s catatan kanari sah": "The hash chain of %(n)s canary records is valid",
    "Log utuh": "Log intact",
    "Rantai hash log kanari tidak utuh. Kueri di bawah tidak dapat dijadikan bukti sampai penyebabnya jelas.":
        "The canary log\u2019s hash chain is broken. The queries below cannot serve as evidence until the cause is clear.",
    "Waktu": "Time",
    "Resolver": "Resolver",
    "Tindakan": "Actions",
    "Nama penerima sengaja tidak ditampilkan: kueri kanari adalah bukti pendukung, bukan hasil atribusi. Hubungkan nomor salinan dengan penerimanya lewat Lacak.":
        "Recipient names are left out on purpose: a canary query is supporting evidence, not an attribution. Match the copy number to its recipient through Trace.",
    "Dokumen terbitan": "Issued documents",
    "%(docs)s dokumen, %(copies)s salinan bertanda.": "%(docs)s documents, %(copies)s marked copies.",
    "Diterbitkan": "Issued",
    "dilacak %(num)s kali": ("traced %(num)s time", "traced %(num)s times"),
    "Penerbit: %(who)s": "Issuer: %(who)s",
    "%(n)s berkas akar ditulis ke <span class=\"mono\">%(folder)s</span>": "%(n)s root files written to <span class=\"mono\">%(folder)s</span>",
    "sementara": "provisional",
    "Akar hari berjalan bersifat sementara: berubah bila hari ini ada entri baru.": "Today\u2019s root is provisional: it changes if there are new entries today.",
    "Tidak ada entri untuk diekspor.": "No entries to export.",
    "Belum ada": "None yet",

    # ---------------------------------------------------------------- messages written by app.py
    "Huruf kembar": "Look-alike letters",
    "Pilihan kata": "Word choice",
    "Varian kalimat (OCR gambar)": "Sentence variants (image OCR)",
    "Pilihan kata (OCR gambar)": "Word choice (image OCR)",
    "Karakter tak terlihat dan huruf kembar": "Invisible characters and look-alike letters",
    "1 dari 10.000": "1 in 10,000",
    "1 dari 1.000.000": "1 in 1,000,000",
    "1 dari 100.000.000": "1 in 100,000,000",
    "1 dari %(n)s": "1 in %(n)s",
    "PDF ini tidak memiliki lapisan teks dan tidak dikenali sebagai hasil pindai (setiap halaman pindaian harus berupa satu gambar halaman penuh). Tidak ada yang dapat ditandai.":
        "This PDF has no text layer and is not recognised as a scan (every scanned page must be one full-page image). There is nothing to mark.",
    "Penerbitan sedang berjalan. Keputusan tidak dapat diubah lagi; tunggu hasilnya.": "Issuing is running. Decisions can no longer change; wait for the result.",
    "Permintaan dari asal lain ditolak.": "A request from another origin was refused.",
    "identitas penerima hanya berasal dari catatan lokal dan belum dikonfirmasi.": "the recipient\u2019s identity comes from local records only and is not confirmed.",
    "Dokumen ini tidak tercatat di registri.": "This document is not recorded in the registry.",
    "identitas penerima belum dikonfirmasi oleh rantai bertanda tangan.": "the recipient\u2019s identity is not yet confirmed by a signed chain.",
    "registri tidak diverifikasi karena kunci publik tidak tersedia": "the registry was not verified because the public key is not available",
    "identitas penerima belum dilindungi tanda tangan registri.": "the recipient\u2019s identity is not yet protected by a registry signature.",
    "kanal %(a)s dan kanal %(b)s": "the %(a)s channel and the %(b)s channel",
    "halaman %(n)s": "page %(n)s",
    "%(n)s halaman dibaca": "%(n)s pages read",
    "slot terbaca %(n)s dari %(total)s": "slots read %(n)s of %(total)s",
    "bit terbaca %(n)s dari %(total)s": "bits read %(n)s of %(total)s",
    "halaman tidak dikenali": "page not recognised",
    "pola tidak terdeteksi": "pattern not detected",
    "%(n)s tanda di luar gambar, tidak dibaca": "%(n)s marks outside the image, not read",
    "OCR gagal membaca halaman": "OCR could not read the page",
    "dibaca dengan OCR dalam %(s)s detik": "read with OCR in %(s)s seconds",
    "uji pola z = %(z)s": "pattern test z = %(z)s",
    "korelasi %(r)s": "correlation %(r)s",
    "resolusi efektif %(dpi)s dpi": "effective resolution %(dpi)s dpi",
    "Permintaan tidak dapat dibaca. Periksa isian dan berkas, lalu kirim lagi.": "The request could not be read. Check the form and the files, then send again.",
    "Halaman tidak ditemukan. Periksa alamatnya, atau pilih tujuan dari menu.": "Page not found. Check the address, or pick a destination from the menu.",
    "Tindakan ini tidak tersedia di alamat tersebut.": "This action is not available at that address.",
    "Kiriman terlalu besar (maksimum 40 MB seluruhnya).": "The upload is too large (40 MB in total at most).",
    "Teks yang ditempel terlalu panjang (maksimum 1 MB). Simpan sebagai berkas .txt lalu unggah.":
        "The pasted text is too long (1 MB at most). Save it as a .txt file and upload that.",
    "Permintaan ditolak (kode %(code)s).": "Request refused (code %(code)s).",
    "Isian tidak sah: %(fields)s. Periksa lalu kirim lagi.": "Invalid fields: %(fields)s. Check them and send again.",
    "Terjadi kesalahan tak terduga di server TAPAK. Coba lagi; bila berulang, periksa log server.":
        "Something unexpected went wrong on the TAPAK server. Try again; if it happens again, check the server log.",
    "Berkas terlalu besar (maksimum 40 MB)": "The file is too large (40 MB at most)",
    "Dokumen tidak memiliki halaman": "The document has no pages",
    "Pratinjau dokumen tidak dapat dibuat": "The document preview could not be made",
    "Pratinjau hanya tersedia untuk dokumen PDF": "Previews are available for PDF documents only",
    "Sesi penerbitan tidak ditemukan atau sudah kedaluwarsa.": "The issuing session was not found or has expired.",
    "PDF ini terlalu besar (maksimum 40 MB).": "This PDF is too large (40 MB at most).",
    "CSV ini terlalu besar (maksimum 40 MB).": "This CSV is too large (40 MB at most).",
    "Pilih berkas PDF dokumen induk.": "Choose the master document\u2019s PDF file.",
    "Berkas ini bukan PDF. Ekspor dokumen ke PDF lalu unggah lagi.": "This file is not a PDF. Export the document to PDF and upload it again.",
    "Pilih berkas CSV daftar penerima.": "Choose the recipient list\u2019s CSV file.",
    "CSV harus memiliki kolom recipient_id dan nama.": "The CSV must have the columns recipient_id and nama.",
    "CSV harus berenkode UTF-8.": "The CSV must be UTF-8 encoded.",
    "Ukuran koalisi harus bilangan bulat antara 1 dan 10.": "The coalition size must be a whole number from 1 to 10.",
    "Pilih salah satu tingkat peluang tuduhan salah.": "Choose one of the false-accusation levels.",
    "Pilih skema geser v1 atau v2.": "Choose shift scheme v1 or v2.",
    "PDF tidak dapat dibaca.": "The PDF cannot be read.",
    "Dokumen ini sudah pernah diterbitkan.": "This document has already been issued.",
    "Penerbitan ditolak: TAPAK tidak dapat menggambar ulang dokumen ini tanpa perubahan yang terlihat (selisih maksimum %(n)s tingkat abu-abu).":
        "Issuing refused: TAPAK cannot redraw this document without a visible change (largest difference %(n)s grey levels).",
    "berbeda": "different",
    "Tidak ada titik pilihan kata di dokumen ini. Salinan diterbitkan tanpa kanal pilihan kata.":
        "This document has no word-choice points. The copies are issued without the word-choice channel.",
    "%(n)s dari %(total)s titik pilihan kata menunggu tinjauan Anda.": "%(n)s of %(total)s word-choice points await your review.",
    "Semua titik pilihan kata sudah ditinjau.": "Every word-choice point has been reviewed.",
    "%(lex)s bit pilihan kata + %(sem)s bit varian kalimat.": "%(lex)s word-choice bits + %(sem)s sentence-variant bits.",
    "Cukup untuk satu pembocor.": "Enough for one leaker.",
    "Belum cukup untuk satu pembocor.": "Not enough for one leaker yet.",
    "Permintaan tidak valid": "Invalid request",
    "Pilihan kata hanya tersedia untuk dokumen induk PDF.": "Word choice is available for PDF masters only.",
    "Pilihan kata %(why)s.": "Word choice is %(why)s.",
    "Pemindaian tidak dapat dilakukan: %(why)s": "The scan could not run: %(why)s",
    "Persetujuan sekaligus memerlukan konfirmasi. Baca setiap kalimatnya, lalu setujui satu per satu atau konfirmasi persetujuan sekaligus.":
        "Approving all at once needs a confirmation. Read every sentence, then approve them one by one or confirm the approval of all.",
    "Varian tidak dapat dibuat: %(why)s": "The variants could not be made: %(why)s",
    "Varian dari model bahasa harus disetujui satu per satu.": "Variants from a language model must be approved one by one.",
    "Penerbitan diblokir: %(n)s titik pilihan kata masih menunggu keputusan (titik %(shown)s). Setujui atau tolak setiap titik terlebih dahulu.":
        "Issuing blocked: %(n)s word-choice points still await a decision (points %(shown)s). Approve or reject every point first.",
    "Penerbitan gagal: %(why)s": "Issuing failed: %(why)s",
    "Dokumen ini sudah pernah diterbitkan. Buka halaman Lacak untuk dokumen tersebut, atau mulai lagi dengan dokumen lain.":
        "This document has already been issued. Open the Trace page for it, or start over with another document.",
    "Salinan tidak ditemukan": "Copy not found",
    "Nama berkas salinan di catatan penerbitan tidak valid": "The copy file name in the issuance record is invalid",
    "Berkas salinan tidak ditemukan": "Copy file not found",
    "Bukti terlalu besar (maksimum 40 MB seluruhnya). Pilih lebih sedikit berkas atau foto yang lebih kecil.":
        "The evidence is too large (40 MB in total at most). Choose fewer files or smaller photos.",
    "%(name)s: jenis berkas tidak dikenal. Unggah foto, tangkapan layar, PDF, DOCX, atau TXT.":
        "%(name)s: unknown file type. Upload a photo, a screenshot, a PDF, a DOCX or a TXT.",
    "Pilih dokumen yang diduga bocor.": "Choose the document suspected of leaking.",
    "Unggah foto, tangkapan layar, PDF, atau DOCX, atau tempel teksnya.": "Upload a photo, a screenshot, a PDF or a DOCX, or paste its text.",
    "Kanal geser tidak membaca halaman pindaian (lihat peringatan di atas); pola latar halaman itu tetap dibaca.":
        "The shift channel did not read the scanned pages (see the warning above); those pages\u2019 background pattern was still read.",
    "Kanal geser mencakup halaman pindaian: kotak katanya dibaca ulang dengan Tesseract dan cocok dengan catatan penerbitan.":
        "The shift channel covers the scanned pages: their word boxes were read again with Tesseract and match the issuance record.",
    "isi berkas bukan teks; kunci publik berupa 64 karakter heksadesimal": "the file is not text; a public key is 64 hexadecimal characters",
    "berkas tidak dapat dibaca (%(why)s)": "the file cannot be read (%(why)s)",
    # ---------------------------------------------------------------- fixed sentences of the core library
    # decoder
    "tidak cukup bukti": "not enough evidence",
    "tidak ada tanda yang terbaca pada bukti": "no mark could be read in the evidence",
    "kanal pilihan kata dilewati": "word-choice channel skipped",
    "pilihan kata saat penerbitan (leksikal.json) tidak tersedia": "the word choices of the issuance (leksikal.json) are not available",
    "pilihan kata (leksikal.json) tidak cocok dengan catatan penerbitan": "the word choices (leksikal.json) do not match the issuance record",
    "kanal geser halaman pindaian dilewati": "shift channel of the scanned pages skipped",
    "halaman pindaian dokumen induk tidak sama dengan catatan penerbitan": "the master\u2019s scanned pages differ from the issuance record",
    "dokumen induk tidak dapat dibuka (bukan PDF yang sah atau rusak)": "the master document cannot be opened (not a valid PDF, or damaged)",
    "dokumen induk tidak cocok dengan catatan penerbitan (hash berbeda)": "the master document does not match the issuance record (different hash)",
    "dokumen induk DOCX tidak dapat dibaca (rusak atau bukan DOCX)": "the DOCX master cannot be read (damaged, or not a DOCX)",
    "varian semantik saat penerbitan tidak tersedia": "the semantic variants of the issuance are not available",
    "varian semantik tidak cocok dengan catatan penerbitan": "the semantic variants do not match the issuance record",
    "kanal semantik dilewati": "semantic channel skipped",
    "lapisan teks OCR": "OCR text layer",
    "tanpa lapisan teks yang cocok": "no matching text layer",
    "diperkecil, digeser, atau ukuran kertas berbeda": "shrunk, moved, or a different paper size",
    "halaman sebelumnya tidak cocok dengan dokumen induk": "the pages before did not match the master document",
    "(tanpa akhiran)": "(no extension)",
    "kanal geser serta varian kalimat dan pilihan kata yang dibaca dengan OCR":
        "the shift channel and the sentence variants and word choices read with OCR",
    "kanal geser": "the shift channel",
    "teks dan OCR gambar": "text and image OCR",
    "pembacaan digital (tanpa derau terukur)": "digital reading (no measured noise)",
    "kemungkinan salah satu kanal dimanipulasi": "one of the channels may have been tampered with",
    "Tesseract tidak tersedia": "Tesseract is not available",
    "Tesseract tidak terpasang": "Tesseract is not installed",
    "data bahasa Indonesia Tesseract (tesseract-ocr-ind) tidak terpasang": "Tesseract\u2019s Indonesian language data (tesseract-ocr-ind) is not installed",
    "pengodean gambar untuk Tesseract gagal": "encoding the image for Tesseract failed",
    "Tesseract gagal membaca halaman": "Tesseract could not read the page",
    "Tesseract tidak terpasang; halaman pindaian memerlukan tesseract-ocr dan tesseract-ocr-ind":
        "Tesseract is not installed; scanned pages need tesseract-ocr and tesseract-ocr-ind",
    "Tesseract gagal membaca halaman pindaian": "Tesseract could not read the scanned page",
    # the manipulation checks
    "tanda di posisi yang hampir pasti sama di semua salinan terbaca terbalik (pola tanda terbalik)":
        "marks at positions that are almost surely the same in every copy read reversed (reversed-mark pattern)",
    "tanda hilang justru di posisi tempat salinan koalisi kemungkinan sama (pola penghapusan)":
        "marks are missing exactly where the colluders\u2019 copies probably agree (erasure pattern)",
    "bukti terbaca jelas, tetapi tidak ada salinan yang mencapai ambang (bacaan jelas tanpa nama)":
        "the evidence reads clearly, but no copy reaches the threshold (clear reading, no name)",
    "menghapus": "erased",
    "membalik": "reversed",
    "menghapus atau membalik": "erased or reversed",
    "membalik atau mengacak": "reversed or scrambled",
    "menghapus, membalik, atau mengacak": "erased, reversed or scrambled",
    "atau masalah pembacaan bukti": "or a problem reading the evidence",
    "masalah pembacaan bukti": "a problem reading the evidence",
    "pemeriksaan ini": "this check",
    "setiap pemeriksaan ini": "each of these checks",
    "pola penghapusan: untuk dokumen tertentu laju alarm palsunya dapat sampai beberapa persen":
        "erasure pattern: for some documents its false-alarm rate can reach a few percent",
    "Ini hanya peringatan: tidak ada nama yang disebut karenanya, dan putusan, ambang, serta skor tidak berubah":
        "This is only a warning: nobody is named because of it, and the verdict, the thresholds and the scores do not change",
    "tidak diperiksa: tidak ada tanda yang terbaca": "not checked: no mark was read",
    # registry check of a trace, and the notes of service.py
    "registri tidak ditemukan": "registry not found",
    "kunci publik tidak tersedia": "public key not available",
    "rantai tidak diverifikasi": "chain not verified",
    "dokumen tercatat lebih dari sekali": "the document is recorded more than once",
    "entri dokumen tidak ada": "the document entry is missing",
    "rantai tanpa tanda tangan tidak terlindungi dari pemalsuan oleh pemegang akses tulis":
        "a chain without signatures is not protected against forgery by anyone with write access",
    "pelacakan ini tidak dicatat di registri, jadi pelacakan berulang atas dokumen ini tidak diperhitungkan: pelacakan "
    "ini memakai seluruh eps dan batas peluang tuduhan salah hanya berlaku untuk pelacakan ini saja":
        "this trace is not recorded in the registry, so repeated traces of this document are not accounted for: this "
        "trace uses all of eps, and the false-accusation bound holds for this trace alone",
    "entri pelacakan ini dicatat di registri tanpa tanda tangan": "this trace\u2019s entry is recorded in the registry without a signature",
    "pemegang kunci menandatanganinya dengan tapak registry sign": "the key holder signs it with tapak registry sign",
    "dokumen ini diterbitkan tanpa registri": "this document was issued without a registry",
    "identitas penerima hanya berasal dari catatan lokal dan tidak dapat dikonfirmasi pihak ketiga":
        "the recipient\u2019s identity comes from local records only and cannot be confirmed by a third party",
    "kode dokumen tidak valid": "invalid document key",
    "registri memiliki entri yang belum ditandatangani": "the registry has entries that are not signed yet",
    "pemegang kunci perlu menjalankan tapak registry sign lebih dulu": "the key holder needs to run tapak registry sign first",
    "kanal pilihan kata hanya tersedia untuk dokumen induk PDF": "the word-choice channel is available for PDF masters only",
    "id salinan tetap (benih riset) hanya tersedia untuk dokumen induk PDF": "fixed copy ids (research seed) are available for PDF masters only",
    "log jangkar tidak boleh berkas registri itu sendiri": "the anchor log must not be the registry file itself",
    "pilih berkas di penyimpanan terpisah": "choose a file on separate storage",
    # issuing (marker/)
    "Latar profil cetak: halaman akan tampak abu-abu muda, baik di layar maupun di kertas, dan tekstur polanya mungkin "
    "terlihat bila diperhatikan. Pakai profil ini hanya bila salinan akan dicetak dan Anda menerima tampilan itu.":
        "Print-profile background: pages look light grey, on screen and on paper, and the texture of the pattern may "
        "show on close inspection. Use this profile only when the copies will be printed and you accept that look.",
    "Untuk dokumen cetak, pilihan kata mengambil lebih banyak posisi geser daripada yang dikembalikan OCR: pada nota "
    "dinas contoh 439 menjadi 314 posisi geser (bersama varian kalimat), sedangkan OCR mengembalikan paling banyak 9 bit "
    "per halaman; dalam uji foto cetak simulasi (profil latar bawaan), penerbitan tanpa pilihan kata dan varian kalimat "
    "menyebut salinan yang benar sama sering atau lebih sering di setiap sel":
        "For a printed document, word choice takes more shift positions than OCR gives back: on the sample memo 439 "
        "become 314 shift positions (together with sentence variants), while OCR returns at most 9 bits per page; in the "
        "simulated print-photo tests (default background profile), issuing without word choice and sentence variants "
        "named the right copy as often or more often in every cell",
    "judul paragraf": "paragraph heading",
    "konteks aturan tidak cocok": "the rule\u2019s context does not match",
    "kalimat memuat unsur terlindungi": "the sentence holds a protected element",
    "tidak muat pada baris": "does not fit the line",
    "baris memakai lebih dari satu jenis huruf": "the line uses more than one typeface",
    "huruf tidak tersedia pada font": "a letter is missing from the font",
    "dengan kepadatan dokumen ini": "at this document\u2019s density",
    "baris titik pilihan kata juga dipakai kanal semantik": "a word-choice point\u2019s line is also used by the semantic channel",
    "berkas pilihan kata dibuat untuk dokumen lain": "the word-choice file was made for another document",
    "status titik pilihan kata tidak dikenal": "unknown word-choice point status",
    "titik di berkas pilihan kata diubah di luar TAPAK (digest pemindaian tidak cocok); pindai ulang dengan tapak "
    "leksikal scan":
        "points in the word-choice file were changed outside TAPAK (the scan digest does not match); scan again with "
        "tapak leksikal scan",
    "leksikon berubah sejak pemindaian; pindai ulang dokumen": "the lexicon changed since the scan; scan the document again",
    "titik pilihan kata tidak cocok dengan pemindaian ulang dokumen induk; pindai ulang dengan tapak leksikal scan":
        "the word-choice points do not match a new scan of the master document; scan again with tapak leksikal scan",
    "bukan berkas pilihan kata TAPAK": "not a TAPAK word-choice file",
    "berkas pilihan kata rusak": "the word-choice file is damaged",
    "daftar penerima kosong": "the recipient list is empty",
    "setiap baris wajib memiliki recipient_id dan nama": "every row must have a recipient_id and a nama (name)",
    "id salinan harus 16 karakter heksadesimal huruf kecil": "copy ids must be 16 lowercase hexadecimal characters",
    "id salinan tidak boleh ganda": "copy ids must not repeat",
    "jumlah penerima melebihi n_max kode": "the number of recipients exceeds the code\u2019s n_max",
    "dokumen induk bukan berkas PDF": "the master document is not a PDF file",
    "dokumen induk PDF tidak dapat dibuka atau rusak": "the PDF master cannot be opened or is damaged",
    "gerbang visual gagal: salinan tanpa tanda dari halaman pindaian tidak identik piksel demi piksel dengan gambar "
    "halaman dokumen induk, atau tampilan halamannya berbeda":
        "visual gate failed: the unmarked copy of the scanned pages does not match the master page image pixel for "
        "pixel, or its page looks different",
    # scanned pages (marker/raster.py)
    "masker warna": "a colour mask",
    "masker transparansi": "a transparency mask",
    "konten opsional": "optional content",
    "gambar halaman pindaian diputar atau dibalik; halaman seperti ini belum didukung":
        "the scanned page image is rotated or flipped; such pages are not supported yet",
    "gambar halaman pindaian memiliki masker transparansi; halaman seperti ini belum didukung":
        "the scanned page image has a transparency mask; such pages are not supported yet",
    "gambar halaman pindaian tersisip langsung di isi halaman; halaman seperti ini belum didukung":
        "the scanned page image is inlined in the page content; such pages are not supported yet",
    "gambar yang sama dipakai di beberapa halaman; halaman seperti ini belum didukung":
        "the same image is used on several pages; such pages are not supported yet",
    "gambar halaman pindaian tidak memiliki ruang warna": "the scanned page image has no colour space",
    "ukuran gambar halaman pindaian berubah": "the size of the scanned page image changed",
    "salinan halaman pindaian berubah di luar batas kanal (pola latar terlalu kuat)":
        "the copy of the scanned page changed beyond the channel\u2019s limits (background pattern too strong)",
    "salinan halaman pindaian mengubah tinta di luar kata yang digeser": "the copy of the scanned page changes ink outside the shifted words",
    "Halaman pindaian membawa kanal geser (kotak kata dari Tesseract, ditanam pada piksel gambar) dan pola latar; "
    "karakter tak terlihat, huruf kembar, varian semantik, dan pilihan kata tidak berlaku di sana":
        "Scanned pages carry the shift channel (word boxes from Tesseract, placed in the image pixels) and the background "
        "pattern; invisible characters, look-alike letters, semantic variants and word choice do not apply there",
    # sentences that may not be reworded, and rejected proposals (marker/semantic.py)
    "kalimat terlalu pendek untuk diparafrasekan": "the sentence is too short to reword",
    "mengandung angka": "contains digits",
    "menyebut waktu atau tanggal": "names a time or a date",
    "menyebut koordinat atau posisi": "names coordinates or a position",
    "mengandung kata berhuruf kapital selain kata pertama (nama, satuan, atau jabatan)":
        "contains capitalised words other than the first (a name, unit or position)",
    "mengandung kata perintah, larangan, atau tenggat": "contains an order, a prohibition or a deadline",
    "mengandung kata ingkar": "contains a negation",
    "menyebut bilangan": "names a number",
    "unit bukan kalimat utuh: baris sebelumnya belum mengakhiri kalimat": "not a whole sentence: the line before has not ended its sentence",
    "unit bukan kalimat utuh: tidak diakhiri titik, tanda seru, atau tanda tanya": "not a whole sentence: it does not end with a full stop, exclamation mark or question mark",
    "unit bukan kalimat utuh: baris terakhir penuh sehingga paragraf dapat berlanjut": "not a whole sentence: the last line is full, so the paragraph may continue",
    "kalimat asli tidak dapat ditata ulang pada baris yang sama": "the original sentence cannot be laid out again on the same lines",
    "baris unit harus berurutan": "the unit\u2019s lines must be consecutive",
    "baris unit berada di luar halaman": "the unit\u2019s lines are outside the page",
    "unit harus memakai satu jenis huruf, ukuran, dan warna": "the unit must use one typeface, size and colour",
    "semua baris unit harus dimulai pada posisi kiri yang sama": "every line of the unit must start at the same left position",
    "memuat tanda baca atau karakter yang tidak ada pada kalimat asli": "has punctuation or characters the original sentence does not have",
    "tanda akhir kalimat berubah": "the sentence\u2019s final punctuation changed",
    "token terlindungi berubah (angka, nama, atau kata kunci)": "a protected token changed (a number, name or keyword)",
    "tidak muat tepat pada baris yang sama": "does not fit exactly on the same lines",
    "kandidat kosong": "empty candidate",
    "sama dengan kalimat asli": "the same as the original sentence",
    "duplikat atau terlalu mirip dengan varian lain": "a duplicate of, or too close to, another variant",
    "status varian tidak dikenal": "unknown variant status",
    "status kalimat asli tidak dapat diubah": "the original sentence\u2019s status cannot be changed",
    "indeks varian tidak valid": "invalid variant index",
    "kalimat asli (varian 0) harus berstatus disetujui": "the original sentence (variant 0) must be approved",
    # registry verification and keys (registry/)
    "mata rantai terputus: prev_hash tidak sama dengan hash entri sebelumnya": "broken link: prev_hash differs from the previous entry\u2019s hash",
    "entri pelacakan untuk dokumen yang tidak tercatat sebelumnya di registri": "a trace entry for a document not recorded earlier in the registry",
    "eps entri pelacakan berbeda dari eps entri dokumennya": "the trace entry\u2019s eps differs from its document entry\u2019s eps",
    "waktu di isi entri pelacakan berbeda dari waktu entri": "the time in the trace entry\u2019s payload differs from the entry\u2019s time",
    "hash entri berbeda dari jangkar yang dicatat (entri ini atau entri sebelumnya diubah)": "the entry hash differs from the recorded anchor (this entry or an earlier one was changed)",
    "berkas registri tidak ditemukan": "registry file not found",
    "berkas bukan registri TAPAK yang dapat dibaca (bukan SQLite atau tabel entri tidak ada)": "the file is not a readable TAPAK registry (not SQLite, or no entries table)",
    "registri kosong: tidak ada entri untuk diverifikasi (jika sebelumnya ada entri, semuanya telah dihapus)": "the registry is empty: no entries to verify (if there were entries, all of them were deleted)",
    "waktu di isi entri log jangkar berbeda dari waktu entri": "the time in the anchor log entry\u2019s payload differs from the entry\u2019s time",
    "waktu pencatatan mundur dibanding entri sebelumnya": "the recording time goes back compared with the previous entry",
    "waktu pencatatan tidak sah": "invalid recording time",
    "tanda tangan atau kunci penanda tangan tidak lengkap": "the signature or the signer key is incomplete",
    "tanda tangan tidak sah untuk hash entri ini": "the signature is not valid for this entry\u2019s hash",
    "isi entri bukan teks JSON": "the entry payload is not JSON text",
    "isi entri bukan JSON yang sah": "the entry payload is not valid JSON",
    "isi entri bukan objek JSON": "the entry payload is not a JSON object",
    "isi entri tidak dalam bentuk JSON kanonik (diubah di luar TAPAK?)": "the entry payload is not in canonical JSON form (changed outside TAPAK?)",
    "hash entri tidak cocok dengan isinya (isi atau hash diubah)": "the entry hash does not match its payload (payload or hash changed)",
    "itu kunci PRIVAT, bukan kunci publik; gunakan isi berkas .pub": "that is a PRIVATE key, not the public key; use the contents of the .pub file",
    "kunci publik harus 64 karakter heksadesimal": "the public key must be 64 hexadecimal characters",
    "registri tidak dapat dibuka atau ditulis (bukan berkas SQLite, rusak, atau sedang terkunci)": "the registry cannot be opened or written (not an SQLite file, damaged, or locked)",
    "berkas berisi karakter yang tidak sah": "the file holds invalid characters",
    # anchor log (registry/anchor.py)
    "cocok dengan registri (belum ada entri yang dijangkarkan)": "matches the registry (no entry anchored yet)",
    "berkas atau folder tidak ada": "file or folder missing",
    "tidak ada izin": "no permission",
    "tidak diizinkan": "not allowed",
    "berupa folder": "is a folder",
    "penyimpanan hanya-baca": "read-only storage",
    "penyimpanan penuh": "storage full",
    "galat masukan/keluaran penyimpanan": "storage input/output error",
    "jalurnya bukan folder": "the path is not a folder",
    "bukan berkas biasa": "not a regular file",
    "penyimpanan jaringan terputus": "network storage disconnected",
    "log jangkar dikunci proses lain terlalu lama": "another process locked the anchor log for too long",
    "nomor urut tidak berurutan": "sequence numbers out of order",
    "mata rantai terputus": "broken link",
    "isi atau hash entri diubah": "an entry\u2019s payload or hash was changed",
    "baris terakhir log jangkar terpotong (penulisan terputus, misalnya mati listrik) dan diabaikan; baris berikutnya "
    "ditulis di baris baru":
        "the last line of the anchor log is cut off (an interrupted write, for example a power cut) and is ignored; the "
        "next line is written on a new line",
    "log jangkar tidak memuat satu baris pun yang sah (kosong, atau isinya dihapus atau rusak)":
        "the anchor log holds no valid line (empty, or its contents were deleted or damaged)",
    "tanda tangan baris log jangkar tidak diperiksa karena kunci publik registri tidak tersedia":
        "the anchor log lines\u2019 signatures were not checked because the registry public key is not available",
    "registri kini kosong atau tidak ada": "the registry is now empty or missing",
    "entri dihapus dari ujung rantai, atau registri diganti salinan yang lebih lama":
        "entries were deleted from the end of the chain, or the registry was replaced with an older copy",
    "entri dihapus dari rantai": "entries were deleted from the chain",
    # canary log (canary_dns/store.py)
    "tabel canary_events tidak ada (terhapus atau belum pernah dibuat)": "the canary_events table is missing (deleted, or never created)",
    "catatan kanari masih kosong": "the canary log is still empty",
    "belum ada jangkar bertanda tangan di registri: penulisan ulang rantai atau pemotongan ujungnya tidak dapat dideteksi":
        "no signed anchor in the registry yet: a rewritten chain or a cut-off end cannot be detected",
    # demo sandbox
    "gambar selisih tidak dapat dibuat": "the difference image could not be made",
    # the local language model (llm/)
    "setara: hanya frasa baku yang diganti dengan padanannya": "equivalent: only standard phrases swapped for their equivalents",
    "token terlindungi (angka, nama, atau kata kunci) berubah": "a protected token (a number, name or keyword) changed",
    "ada perubahan di luar tabel frasa baku yang setara": "there are changes outside the table of equivalent standard phrases",
    "tidak setara": "not equivalent",
    "jawaban pemeriksa tidak dapat dibaca": "the checker\u2019s answer cannot be read",
    "jawaban server LLM lokal tidak dapat dibaca": "the local LLM server\u2019s answer cannot be read",
    "pustaka llama_cpp tidak terpasang; pasang llama-cpp-python, atau kosongkan jalur model dan jalankan server "
    "llama.cpp lokal":
        "the llama_cpp library is not installed; install llama-cpp-python, or clear the model path and run a local "
        "llama.cpp server",
}

# ---------------------------------------------------------------- sentences of the core library
# (Indonesian template, English template). A placeholder matches any text; {x:t} is translated
# itself, {x:l} is a "; " list and {x:c} a ", " list whose items are translated one by one.
# Numbers in the other placeholders are rewritten the English way. Tried in order, on the whole
# sentence first; a sentence no rule matches is split at "; " and its clauses tried one by one.
RULES: list[tuple[str, str]] = [
    # trace notes (decoder/trace.py, decoder/accuse.py, service.py)
    ("berkas identik byte demi byte dengan salinan #{n} (bukti pendukung)",
     "the file is byte for byte identical to copy #{n} (supporting evidence)"),
    ("{name}: dipetakan ke halaman {p} (metode {m}, korelasi {r}, resolusi efektif {dpi} dpi)",
     "{name}: mapped to page {p} (method {m}, correlation {r}, effective resolution {dpi} dpi)"),
    ("{name}: pola latar tidak terdeteksi (kertas cetak, foto terlalu terang, atau bukan salinan bertanda); hanya "
     "{used:t} yang dipakai",
     "{name}: background pattern not detected (printed paper, a photo too bright, or not a marked copy); only {used} "
     "was used"),
    ("{name}: halaman dokumen induk tidak ditemukan pada gambar (bukan dokumen ini, terlalu buram, atau terpotong)",
     "{name}: no page of the master document was found in the image (not this document, too blurry, or cropped)"),
    ("{name}: sebagian karakter tidak dapat diterjemahkan (pengodean teks tidak dikenal)",
     "{name}: some characters could not be decoded (unknown text encoding)"),
    ("{name}: bukan berkas PDF yang sah", "{name}: not a valid PDF file"),
    ("{name}: berkas PDF tidak dapat dibuka atau rusak", "{name}: the PDF file cannot be opened or is damaged"),
    ("{name}: berkas DOCX tidak dapat dibaca", "{name}: the DOCX file cannot be read"),
    ("{name}: berkas bukti tidak dapat dibaca", "{name}: the evidence file cannot be read"),
    ("{name}: {k} halaman tidak dibaca sebagai gambar (batas pembacaan gambar per pelacakan tercapai)",
     "{name}: {k} pages not read as images (the per-trace image reading limit was reached)"),
    ("{name}: {k} halaman berikutnya dilewati", "{name}: the next {k} pages skipped"),
    ("{name} halaman {p}: tidak memiliki lapisan teks yang cocok dan tidak dikenali sebagai halaman dokumen induk",
     "{name} page {p}: has no matching text layer and is not recognised as a page of the master document"),
    ("{name} halaman {p}: dibaca sebagai gambar ({why:t}), dipetakan ke halaman {q} (halaman pindaian, korelasi {r})",
     "{name} page {p}: read as an image ({why}), mapped to page {q} (scanned page, correlation {r})"),
    ("{name} halaman {p}: dibaca sebagai gambar ({why:t}), dipetakan ke halaman {q} (korelasi {r})",
     "{name} page {p}: read as an image ({why}), mapped to page {q} (correlation {r})"),
    ("{n} berkas bukti digabung dalam satu atribusi", "{n} evidence files combined into one attribution"),
    ("{reason:t}: varian kalimat dan pilihan kata pada gambar tidak dibaca (OCR)",
     "{reason}: sentence variants and word choices in the image were not read (OCR)"),
    ("jenis berkas tidak dikenal: {s:t}", "unknown file type: {s}"),
    ("tidak cukup bukti: bukti ini hanya memuat tanda yang bertahan saat diketik ulang (pilihan kata dan varian "
     "kalimat), {bits} bit. TAPAK baru menyebut satu pembocor dari teks ketikan ulang mulai {lone} bit, kira-kira "
     "dokumen dengan {words} kata isi. Dokumen ini memuat {doc} kata isi.",
     "not enough evidence: this evidence carries only marks that survive retyping (word choice and sentence "
     "variants), {bits} bits. TAPAK names a single leaker from retyped text only from {lone} bits, roughly a document "
     "of {words} content words. This document has {doc} content words."),
    ("tidak cukup bukti: bukti ini hanya memuat tanda yang bertahan saat diketik ulang (pilihan kata dan varian "
     "kalimat), {bits} bit. TAPAK baru menyebut satu pembocor dari teks ketikan ulang mulai {lone} bit, kira-kira "
     "dokumen dengan {words} kata isi.",
     "not enough evidence: this evidence carries only marks that survive retyping (word choice and sentence "
     "variants), {bits} bits. TAPAK names a single leaker from retyped text only from {lone} bits, roughly a document "
     "of {words} content words."),
    ("salinan {seqs}: nama ini hanya didukung tanda yang terlihat di kertas (pilihan kata, varian kalimat); tanpa "
     "tanda itu salinan ini tidak mencapai ambang",
     "copy {seqs}: this name rests only on marks visible on paper (word choice, sentence variants); without them this "
     "copy does not reach the threshold"),
    ("salinan {seqs}: nama ini hanya didukung tanda yang terlihat di kertas (pilihan kata, varian kalimat); tanpa "
     "tanda itu salinan ini tidak mencapai ambang. Siapa pun yang pernah membaca salinan ini dapat meniru pilihan "
     "katanya saat mengetik ulang, jadi hasil ini menunjuk pilihan kata salinan tersebut, bukan pengetiknya, dan "
     "memerlukan bukti pendukung",
     "copy {seqs}: this name rests only on marks visible on paper (word choice, sentence variants); without them this "
     "copy does not reach the threshold. Anyone who has read this copy can imitate its word choices when retyping, so "
     "this result points to that copy\u2019s word choices, not to whoever typed it, and needs supporting evidence"),
    ("tahap {n}: dituduh berdasarkan salinan yang sudah dituduh {seqs}",
     "stage {n}: accused on the basis of copies already accused {seqs}"),
    ("{pair} saling bertentangan pada {d} dari {s} posisi", "{pair} disagree at {d} of {s} positions"),
    ("kanal geser halaman pindaian dilewati: {why:t}", "shift channel of the scanned pages skipped: {why}"),
    ("kotak kata tidak dapat dibaca ulang ({e:t})", "the word boxes could not be read again ({e})"),
    ("kotak kata hasil Tesseract berbeda dari saat penerbitan (sekarang {now}, saat penerbitan {then}); TAPAK tidak "
     "menebak letak kata, pola latar tetap dibaca",
     "Tesseract\u2019s word boxes differ from issuance (now {now}, at issuance {then}); TAPAK does not guess where the words "
     "were, and the background pattern is still read"),
    ("{name} rusak atau bukan berkas varian TAPAK", "{name} is damaged or not a TAPAK variant file"),
    ("{name} rusak atau bukan berkas pilihan kata TAPAK", "{name} is damaged or not a TAPAK word-choice file"),
    ("komitmen kode salinan #{n} tidak cocok: rahasia kode salah atau catatan diubah",
     "the code commitment of copy #{n} does not match: wrong code secret, or the record was changed"),
    ("komitmen kode salinan #{n} tidak cocok", "the code commitment of copy #{n} does not match"),
    ("dokumen {key} tidak ditemukan", "document {key} not found"),

    # read noise of a sub-channel (decoder/report.py)
    ("sigma kata {v} pt", "word sigma {v} pt"),
    ("sigma baris {v} pt", "row sigma {v} pt"),
    ("baris dibulatkan ke piksel, langkah {v} pt", "rows rounded to pixels, step {v} pt"),

    # the merged manipulation warning (decoder/manipulation.py), one sentence at a time
    ("bukti kemungkinan diubah oleh orang yang memahami TAPAK: {found:l}",
     "the evidence was probably changed by someone who understands TAPAK: {found}"),
    ("Kemungkinan penyebab: {causes:l}", "Possible causes: {causes}"),
    ("koalisi pemegang dua salinan atau lebih {did:t} tanda di tempat salinannya sama, atau satu salinan membalik "
     "semua tandanya",
     "a coalition holding two or more copies {did} marks where their copies agree, or one copy reversed all its marks"),
    ("koalisi pemegang dua salinan atau lebih {did:t} tanda di tempat salinannya sama",
     "a coalition holding two or more copies {did} marks where their copies agree"),
    ("koalisi lebih dari {n} orang", "a coalition of more than {n} people"),
    ("Pada bukti jujur {which:t} memberi peringatan dengan peluang paling besar sekitar {rate}, rata-rata atas "
     "dokumen, bila derau bacaan tidak bergantung pada kode ({details:l})",
     "On honest evidence {which} gives a warning with a chance of at most about {rate}, averaged over documents, when "
     "the reading noise does not depend on the code ({details})"),
    ("Pada bukti jujur {which:t} memberi peringatan dengan peluang paling besar sekitar {rate}, rata-rata atas "
     "dokumen, bila derau bacaan tidak bergantung pada kode",
     "On honest evidence {which} gives a warning with a chance of at most about {rate}, averaged over documents, when "
     "the reading noise does not depend on the code"),
    ("pola tanda terbalik: {stat:t}", "reversed-mark pattern: {stat}"),
    ("pola penghapusan: {stat:t}, untuk dokumen tertentu laju alarm palsunya dapat sampai beberapa persen",
     "erasure pattern: {stat}, for some documents its false-alarm rate can reach a few percent"),
    ("bacaan jelas tanpa nama: koalisi paling banyak {n} penerima yang tidak mengubah tanda di tempat salinannya sama "
     "lolos dengan peluang terbukti paling besar {b}, bila laju salah bacaan tidak melebihi perkiraannya",
     "clear reading, no name: a coalition of at most {n} recipients that does not change marks where their copies "
     "agree escapes with a proven chance of at most {b}, when the misreading rate does not exceed its estimate"),

    # statistics of the manipulation checks (erasure, reversal, contradiction: text())
    ("z = {z} dari {n} posisi terukur, ambang {t}", "z = {z} from {n} measured positions, threshold {t}"),
    ("tidak diperiksa: hanya {n} posisi terukur (minimal {m})", "not checked: only {n} measured positions (at least {m})"),
    ("{a:t} dan {b:t}, ambang {t} untuk masing-masing", "{a} and {b}, threshold {t} for each"),
    ("z = {z} dengan kekuatan baca latar dari halaman yang polanya ditemukan saja ({n} posisi)",
     "z = {z} with background read strengths only from pages where the pattern was found ({n} positions)"),
    ("z dengan kekuatan baca latar dari halaman yang polanya ditemukan saja tidak dihitung (hanya {n} posisi)",
     "z with background read strengths only from pages where the pattern was found not computed (only {n} positions)"),
    ("z = {z} dengan semua kekuatan baca latar ({n} posisi)", "z = {z} with all background read strengths ({n} positions)"),
    ("z dengan semua kekuatan baca latar tidak dihitung (hanya {n} posisi)",
     "z with all background read strengths not computed (only {n} positions)"),
    ("z pilot = {z} dari {n} halaman gambar, ambang {t}", "z pilot = {z} from {n} image pages, threshold {t}"),
    ("z tanda = {z} dari {n} posisi terbaca, ambang {t}", "z signs = {z} from {n} positions read, threshold {t}"),
    ("z pilot = {z} dari {n} halaman gambar", "z pilot = {z} from {n} image pages"),
    ("z tanda = {z} dari {n} posisi terbaca", "z signs = {z} from {n} positions read"),
    ("batas di atas {rate} (koalisi {c} orang: {b}; {n} posisi terbaca)",
     "bound above {rate} (coalition of {c}: {b}; {n} positions read)"),
    ("batas {b} untuk koalisi paling banyak {c} orang, tidak lebih dari {rate} ({n} posisi terbaca)",
     "bound {b} for a coalition of at most {c}, no more than {rate} ({n} positions read)"),
    ("batas {b} untuk koalisi paling banyak {c} orang, di atas {rate} ({n} posisi terbaca)",
     "bound {b} for a coalition of at most {c}, above {rate} ({n} positions read)"),

    # refusals of a trace (service.py)
    ("pelacakan ditolak sebelum bukti dibaca: {why:t}. Tidak ada nama yang disebut",
     "trace refused before the evidence was read: {why}. No name is given"),
    ("pelacakan ditolak: {why:t}. Tidak ada nama yang disebut", "trace refused: {why}. No name is given"),
    ("{why:t}. Pelacakan dibatalkan sebelum bukti dibaca dan tidak ada nama yang disebut; nomor pelacakan ini tetap "
     "terpakai",
     "{why}. The trace was cancelled before the evidence was read and no name is given; this trace number stays used"),
    ("pelacakan tidak dapat dicatat di registri ({why:t}); pelacakan dibatalkan dan tidak ada nama yang disebut",
     "the trace could not be recorded in the registry ({why}); the trace was cancelled and no name is given"),
    ("dokumen ini tidak ditemukan di registri (berkas registri hilang, terpotong, atau dokumen diterbitkan tanpa "
     "registri), sehingga identitas penerima tidak dapat dikonfirmasi; tidak ada nama yang disebut sampai perbedaan ini "
     "diperiksa",
     "this document was not found in the registry (the registry file is missing or truncated, or the document was "
     "issued without a registry), so the recipient\u2019s identity cannot be confirmed; no name is given until this "
     "difference is checked"),
    ("verifikasi rantai registri gagal ({problems:l}); identitas penerima tidak dapat dikonfirmasi sehingga tidak ada "
     "nama yang disebut. Periksa registri dengan tapak verify",
     "verifying the registry chain failed ({problems}); the recipient\u2019s identity cannot be confirmed, so no name is "
     "given. Check the registry with tapak verify"),
    ("parameter kode di catatan penerbitan lokal tidak cocok dengan registri ({keys:c}); tidak ada nama yang disebut "
     "sampai perbedaan ini diperiksa",
     "the code parameters in the local issuance record do not match the registry ({keys}); no name is given until this "
     "difference is checked"),
    ("catatan penerbitan lokal tidak cocok dengan registri bertanda tangan untuk salinan #{seqs}; tidak ada nama yang "
     "disebut sampai perbedaan ini diperiksa",
     "the local issuance record does not match the signed registry for copies #{seqs}; no name is given until this "
     "difference is checked"),

    # registry check of a trace (service.check_registry)
    ("#{n}: {problem:t}", "#{n}: {problem}"),
    ("{n} salinan tidak cocok dengan registri: #{seqs}", "{n} copies do not match the registry: #{seqs}"),
    ("parameter dokumen tidak cocok dengan registri: {keys:c}", "the document parameters do not match the registry: {keys}"),
    ("{n} entri salinan dokumen ini belum bertanda tangan", "{n} copy entries of this document are not signed yet"),
    ("log kanari: {problem:t}", "canary log: {problem}"),
    ("log kanari tidak dapat diperiksa: {why:t}", "the canary log cannot be checked: {why}"),
    ("kunci tanda tangan {a} tidak cocok dengan kunci publik {b}", "the signing key {a} does not match the public key {b}"),
    ("registri ini memakai log jangkar sejak entri #{n}, tetapi lokasi log jangkar tidak diatur di proses ini. Atur "
     "TAPAK_ANCHOR_LOG atau --log-jangkar ke lokasi log itu; tanpa log itu penghapusan entri dari ujung registri tidak "
     "terperiksa",
     "this registry has used an anchor log since entry #{n}, but the anchor log location is not set in this process. "
     "Set TAPAK_ANCHOR_LOG or --log-jangkar to that log\u2019s location; without it, entries deleted from the end of the "
     "registry go unchecked"),

    # issuing (service.issue_document, marker/issue.py, marker/semantic.py, marker/lexical.py)
    ("penerbitan ditolak: {why:t}", "issuing refused: {why}"),
    ("penerbitan diblokir: {n} titik pilihan kata masih menunggu keputusan ({ids}); setujui atau tolak setiap titik "
     "terlebih dahulu (tapak leksikal review)",
     "issuing blocked: {n} word-choice points still await a decision ({ids}); approve or reject every point first "
     "(tapak leksikal review)"),
    ("penerbitan diblokir: pita bias 0,3 sampai 0,7 hanya memuat {n} posisi kode, sedangkan kanal semantik dan pilihan "
     "kata memerlukan {m} posisi berbeda; tolak sebagian titik pilihan kata atau terbitkan dengan c lebih besar",
     "issuing blocked: the 0.3 to 0.7 bias band holds only {n} code positions, while the semantic and word-choice "
     "channels need {m} different positions; reject some word-choice points or issue with a larger c"),
    ("penerbitan diblokir: titik pilihan kata di halaman {p} tidak muat pada barisnya",
     "issuing blocked: a word-choice point on page {p} does not fit its line"),
    ("penerbitan diblokir: varian semantik untuk unit {units} masih menunggu persetujuan; setujui atau tolak setiap "
     "varian terlebih dahulu",
     "issuing blocked: the semantic variants of unit {units} still await approval; approve or reject every variant first"),
    ("penerbitan diblokir: {why:t}", "issuing blocked: {why}"),
    ("dokumen ini sudah diterbitkan (folder {f}); gunakan dokumen lain", "this document is already issued (folder {f}); use another document"),
    ("dokumen ini sudah diterbitkan (folder {f})", "this document is already issued (folder {f})"),
    ("dokumen ini sedang diterbitkan oleh proses lain (folder {f})", "another process is issuing this document (folder {f})"),
    ("penerbitan dokumen ini sudah tercatat di registri tetapi catatan lokalnya tidak lengkap; periksa folder {f} sebelum "
     "menerbitkan ulang",
     "the issuing of this document is recorded in the registry, but its local record is incomplete; check folder {f} "
     "before issuing again"),
    ("salinan sudah tercatat di registri tetapi catatan lokal gagal ditulis ({e}); folder {f} dipertahankan, jangan "
     "terbitkan ulang",
     "the copies are recorded in the registry, but the local record could not be written ({e}); folder {f} is kept, do "
     "not issue again"),
    ("{why:t}; sampai saat itu pelacakan dan penerbitan ditolak", "{why}; until then tracing and issuing are refused"),
    ("daftar izin kanari tidak dapat ditulis ({e}); kueri untuk salinan ini akan diabaikan pendengar sampai daftar "
     "ditulis ulang dengan tapak kanari-izin",
     "the canary allow list could not be written ({e}); the listener will ignore queries for these copies until the "
     "list is written again with tapak kanari-izin"),
    ("folder kunci {f} berisi rahasia kode dari benih riset, yang publik; penerbitan biasa dan pencatatan di registri "
     "ditolak. Pakai folder kunci lain",
     "key folder {f} holds a code secret from a research seed, which is public; ordinary issuing and registry records "
     "are refused. Use another key folder"),
    ("recipient_id tidak sah: {id}; gunakan huruf, angka, titik, garis bawah atau tanda hubung (maksimal 64 karakter), "
     "karena dipakai dalam nama berkas",
     "invalid recipient_id: {id}; use letters, digits, dots, underscores or hyphens (at most 64 characters), since it "
     "is used in file names"),
    ("jumlah id salinan ({a}) tidak sama dengan jumlah penerima ({b})",
     "the number of copy ids ({a}) differs from the number of recipients ({b})"),
    ("gerbang visual gagal: render ulang tanpa tanda berbeda dari dokumen asli (selisih maks {mx}, rata-rata {mean})",
     "visual gate failed: the unmarked redraw differs from the original document (largest difference {mx}, mean {mean})"),
    ("profil latar tidak dikenal: {p}; pilih 'layar' atau 'cetak'", "unknown background profile: {p}; choose 'layar' (screen) or 'cetak' (print)"),
    ("{bits} bit tahan ketik ulang dari {words} kata isi: cukup untuk satu pembocor (teks ketikan ulang dari satu "
     "salinan); tidak tahan kolusi",
     "{bits} bits survive retyping, from {words} content words: enough for one leaker (retyped text from one copy); not "
     "collusion-resistant"),
    ("{bits} bit tahan ketik ulang: cukup untuk satu pembocor (teks ketikan ulang dari satu salinan); tidak tahan kolusi",
     "{bits} bits survive retyping: enough for one leaker (retyped text from one copy); not collusion-resistant"),
    ("{bits} bit tahan ketik ulang dari {words} kata isi: belum mencapai {lone} bit, batas TAPAK untuk menyebut satu "
     "pembocor dari teks ketikan ulang (kurang {missing} bit, {density:t} kira-kira {more} kata isi lagi)",
     "{bits} bits survive retyping, from {words} content words: short of {lone} bits, TAPAK\u2019s bar for naming one leaker "
     "from retyped text (missing {missing} bits, {density} roughly {more} more content words)"),
    ("{bits} bit tahan ketik ulang: belum mencapai {lone} bit, batas TAPAK untuk menyebut satu pembocor dari teks "
     "ketikan ulang (kurang {missing} bit, {density:t} kira-kira {more} kata isi lagi)",
     "{bits} bits survive retyping: short of {lone} bits, TAPAK\u2019s bar for naming one leaker from retyped text (missing "
     "{missing} bits, {density} roughly {more} more content words)"),
    ("dengan rata-rata tabel ini ({n} bit per 100 kata isi)", "at this table\u2019s average ({n} bits per 100 content words)"),
    ("titik pilihan kata di halaman {p} tidak muat pada barisnya", "a word-choice point on page {p} does not fit its line"),
    ("status tidak dikenal: {s}", "unknown status: {s}"),
    ("titik tidak dikenal: {p}", "unknown point: {p}"),
    ("leksikon {name} tidak dapat dibaca", "lexicon {name} cannot be read"),
    ("leksikon {name} bukan objek JSON", "lexicon {name} is not a JSON object"),
    ("leksikon {name} tidak sah: {why}", "lexicon {name} is invalid: {why}"),
    ("nama leksikon tidak sah: {name}", "invalid lexicon name: {name}"),
    ("tidak lolos pemeriksaan keamanan: {why:c}", "failed the safety checks: {why}"),
    ("tidak setara menurut pemeriksa: {why}", "not equivalent according to the checker: {why}"),
    ("unit {u} tidak cocok dengan dokumen induk", "unit {u} does not match the master document"),
    ("unit {u} tidak boleh diparafrasekan: {why:c}", "unit {u} must not be reworded: {why}"),

    # scanned pages (marker/raster.py)
    ("halaman {p:n}: {problem:t}", "page {p}: {problem}"),
    ("gambar halaman pindaian memakai {what:t} (/{key}); halaman seperti ini belum didukung",
     "the scanned page image uses {what} (/{key}); such pages are not supported yet"),
    ("halaman {p} hasil pindaian beresolusi {dpi} dpi; TAPAK memerlukan minimal {mn} dpi agar geser kata 0,05 mm dan "
     "kotak kata Tesseract cukup andal untuk dibaca kembali. Pindai ulang dokumen pada 300 dpi.",
     "scanned page {p} has a resolution of {dpi} dpi; TAPAK needs at least {mn} dpi for 0.05 mm word shifts and "
     "Tesseract\u2019s word boxes to be read back reliably. Scan the document again at 300 dpi."),
    ("Mode halaman: {n} halaman teks, {s} halaman pindaian (halaman {pages}; {dpi:t} dpi)",
     "Page modes: {n} text, {s} scanned (pages {pages}; {dpi} dpi)"),
    ("Mode halaman: {s} halaman pindaian (halaman {pages}; {dpi:t} dpi)", "Page modes: {s} scanned (pages {pages}; {dpi} dpi)"),
    ("Mode halaman: {n} halaman teks", "Page modes: {n} text"),
    ("{a:n} dan {b:n}", "{a} and {b}"),
    ("Kotak kata: {engine}; hanya hash daftar kotaknya yang dicatat ({digest}...)",
     "Word boxes: {engine}; only the hash of the box list is recorded ({digest}...)"),
    ("Lapisan teks OCR tak terlihat di halaman {pages} tidak disalin ke salinan, karena berisi kata dokumen induk tanpa "
     "tanda",
     "The invisible OCR text layer on pages {pages} is not copied into the copies, since it holds the master\u2019s words "
     "without marks"),
    ("data bahasa Tesseract '{lang}' tidak terpasang (paket tesseract-ocr-ind)",
     "Tesseract language data '{lang}' is not installed (package tesseract-ocr-ind)"),
    ("Tesseract tidak dapat dijalankan ({e})", "Tesseract cannot be run ({e})"),
    ("Tesseract tidak dapat dijalankan (kode keluar {c})", "Tesseract cannot be run (exit code {c})"),
    ("Tesseract tidak selesai dalam {s} detik", "Tesseract did not finish within {s} seconds"),
    ("Tesseract tidak selesai membaca halaman pindaian dalam {s} detik",
     "Tesseract did not finish reading the scanned page within {s} seconds"),

    # registry verification (registry/verify.py, registry/chain.py, registry/signing.py)
    ("mata rantai terputus: prev_hash menunjuk entri #{n}, bukan entri tepat sebelumnya (urutan diubah)",
     "broken link: prev_hash points to entry #{n}, not the entry just before (the order was changed)"),
    ("entri pelacakan: {why:t}", "trace entry: {why}"),
    ("entri dokumen: {why:t}", "document entry: {why}"),
    ("entri log jangkar: {why:t}", "anchor log entry: {why}"),
    ("nomor pelacakan ke-{n}, seharusnya ke-{m} untuk dokumen {doc} (nomor ganda atau terlewat: catatan pelacakan tidak "
     "dapat dipercaya)",
     "trace number {n}, should be {m} for document {doc} (a duplicate or skipped number: the trace record cannot be "
     "trusted)"),
    ("jangkar #{n} tidak ditemukan: entri ini tidak ada lagi di registri (entri di ujung rantai dihapus?)",
     "anchor #{n} not found: this entry is no longer in the registry (entries at the end of the chain deleted?)"),
    ("log jangkar: {why:t}", "anchor log: {why}"),
    ("log jangkar: {n} entri terakhir belum tercatat di log jangkar dan belum terlindungi dari penghapusan; TAPAK "
     "melengkapinya pada penulisan berikutnya",
     "anchor log: the last {n} entries are not yet in the anchor log and not yet protected against deletion; TAPAK "
     "adds them on the next write"),
    ("pemicu hanya-tambah tidak utuh ({which}): berkas pernah disunting di luar TAPAK",
     "the append-only triggers are not intact ({which}): the file was edited outside TAPAK"),
    ("nomor urut bukan bilangan bulat: {v}", "sequence number is not an integer: {v}"),
    ("nomor urut melompat: entri {span} hilang", "sequence number jumps: entries {span} missing"),
    ("nomor urut tidak berurutan (diharapkan #{n})", "sequence numbers out of order (expected #{n})"),
    ("entri {span} tidak bertanda tangan padahal entri #{n} sesudahnya bertanda tangan (tanda tangan dihapus?)",
     "entries {span} are unsigned although entry #{n} after them is signed (signatures deleted?)"),
    ("ditandatangani kunci lain ({key}...), bukan kunci publik yang diperiksa",
     "signed with another key ({key}...), not the public key checked"),
    ("{n} entri ({span}) belum bertanda tangan, jadi tidak terlindungi dari pemalsuan (minta pemegang kunci menjalankan "
     "sign-pending)",
     "{n} entries ({span}) are not signed yet, so they are not protected against forgery (ask the key holder to run "
     "sign-pending)"),
    ("{n} entri ({span}) belum bertanda tangan; entri itu hanya dilindungi rantai hash, yang dapat dihitung ulang oleh "
     "siapa pun yang dapat menulis registri",
     "{n} entries ({span}) are not signed yet; they are protected only by the hash chain, which anyone who can write "
     "the registry can recompute"),
    ("akar Merkle tidak dapat diperiksa: {why:t}", "the Merkle roots cannot be checked: {why}"),
    ("kolom entri pelacakan tidak sesuai skema: kurang {missing}, berlebih {extra}",
     "the trace entry\u2019s fields do not match the schema: missing {missing}, extra {extra}"),
    ("eps_share tidak sesuai jadwal eps x 6 / (pi^2 k^2) untuk pelacakan ke-{n}",
     "eps_share does not follow the schedule eps x 6 / (pi^2 k^2) for trace number {n}"),
    ("isi entri '{kind}' tidak sesuai skema: kurang {missing}, berlebih {extra}",
     "the payload of entry '{kind}' does not match the schema: missing {missing}, extra {extra}"),
    ("isi entri #{n} bukan JSON yang sah (berkas diubah di luar TAPAK?)",
     "the payload of entry #{n} is not valid JSON (file changed outside TAPAK?)"),
    ("jenis entri tidak sah: {kind}", "invalid entry kind: {kind}"),
    ("berkas tidak ditemukan: {f}", "file not found: {f}"),
    ("tidak ada izin mengakses berkas: {f}", "no permission to access the file: {f}"),
    ("itu berkas kunci PRIVAT, gunakan berkas .pub: {f}", "that is a PRIVATE key file, use the .pub file: {f}"),
    ("kunci publik bukan heksadesimal yang sah dan bukan berkas: {v}", "the public key is not valid hexadecimal and not a file: {v}"),
    ("kesalahan berkas: {why}", "file error: {why}"),

    # anchor log (registry/anchor.py)
    ("tidak diatur; entri yang dihapus dari ujung registri hanya terdeteksi dengan log jangkar di penyimpanan terpisah "
     "(tapak jangkar mulai) atau dengan jangkar yang tercetak di berita acara (tapak verify --jangkar)",
     "not set; entries deleted from the end of the registry are detected only with an anchor log on separate storage "
     "(tapak jangkar mulai) or with the anchor printed in the forensic report (tapak verify --jangkar)"),
    ("TIDAK DIATUR, padahal registri ini memakai log jangkar sejak entri #{n}; atur TAPAK_ANCHOR_LOG atau --log-jangkar "
     "ke lokasi log itu",
     "NOT SET, though this registry has used an anchor log since entry #{n}; set TAPAK_ANCHOR_LOG or --log-jangkar to "
     "that log\u2019s location"),
    ("cocok dengan registri sampai entri #{n}", "matches the registry up to entry #{n}"),
    ("{n} entri terakhir ({span}) belum tercatat di log dan dilengkapi pada penulisan berikutnya",
     "the last {n} entries ({span}) are not in the log yet and are added on the next write"),
    ("baris yang tertinggal untuk entri {span} dilengkapi", "the missing lines for entries {span} were added"),
    ("entri baru {span} dicatat di log", "new entries {span} written to the log"),
    ("log memuat {n} pengakuan pemulihan, terakhir {when} ({m} entri dilepas; lihat tapak verify)",
     "the log holds {n} recovery acknowledgements, the last {when} ({m} entries released; see tapak verify)"),
    ("{n} entri pelacakan di antaranya hilang dari registri, jadi nomor dan jatah eps pelacakan itu dapat terpakai lagi "
     "dan batas tuduhan salah gabungan untuk dokumennya tidak lagi terjamin",
     "{n} trace entries among them are gone from the registry, so those trace numbers and eps shares can be used "
     "again and the combined false-accusation bound for their documents is no longer guaranteed"),
    ("log ini dimulai ulang di entri #{n} ({when}) setelah log sebelumnya hilang atau dipindah; entri yang dihapus dari "
     "ujung registri sebelum itu tidak terlihat oleh log ini (periksa dengan log lama atau jangkar berita acara, tapak "
     "verify --jangkar)",
     "this log was started again at entry #{n} ({when}) after the earlier log was lost or moved; entries deleted from "
     "the end of the registry before that are invisible to this log (check with the old log or a forensic report "
     "anchor, tapak verify --jangkar)"),
    ("log ini segmen lanjutan sejak entri #{n} (tapak jangkar rotasi); rotasi itu terbukti sah hanya dengan segmen "
     "lamanya (tapak verify --segmen-lama)",
     "this log is a continuation segment from entry #{n} (tapak jangkar rotasi); that rotation is proven valid only "
     "with its old segment (tapak verify --segmen-lama)"),
    ("peringatan: {w:l}", "warning: {w}"),
    ("TIDAK COCOK dengan registri: {problems:l}", "DOES NOT MATCH the registry: {problems}"),
    ("BELUM DIMULAI: {problems:l}", "NOT STARTED: {problems}"),
    ("HILANG: {problems:l}", "MISSING: {problems}"),
    ("TERLALU BESAR: {problems:l}", "TOO LARGE: {problems}"),
    ("TIDAK TERBACA: {problems:l}", "UNREADABLE: {problems}"),
    ("dan {n} masalah lain", "and {n} more problems"),
    ("dan {n} rentang lain", "and {n} more ranges"),
    ("log jangkar di {f} terlalu besar ({size}, batasnya {limit}), jadi tidak dibaca. Teruskan ke segmen baru dengan "
     "tapak jangkar rotasi BERKAS_BARU (lihat docs/operasi.md)",
     "the anchor log at {f} is too large ({size}, the limit is {limit}), so it is not read. Continue in a new segment "
     "with tapak jangkar rotasi BERKAS_BARU (see docs/operasi.md)"),
    ("log jangkar tidak ditemukan di {f}", "anchor log not found at {f}"),
    ("log jangkar di {f} tidak dapat dibuka ({why:t})", "the anchor log at {f} cannot be opened ({why})"),
    ("log jangkar di {f} bukan berkas biasa", "the anchor log at {f} is not a regular file"),
    ("log jangkar di {f} tidak dapat dibaca ({why:t})", "the anchor log at {f} cannot be read ({why})"),
    ("log jangkar di {f} tidak dapat ditulis ({why:t})", "the anchor log at {f} cannot be written ({why})"),
    ("galat berkas {code}", "file error {code}"),
    ("log jangkar belum dimulai di {f}: jalankan tapak jangkar mulai (lokasi ini diatur lewat TAPAK_ANCHOR_LOG atau "
     "--log-jangkar)",
     "the anchor log has not been started at {f}: run tapak jangkar mulai (this location is set through "
     "TAPAK_ANCHOR_LOG or --log-jangkar)"),
    ("log jangkar sudah {size}; di atas {limit} log tidak dibaca lagi dan semua pelacakan dan penerbitan ditolak. "
     "Teruskan sekarang ke segmen baru dengan tapak jangkar rotasi BERKAS_BARU (lihat docs/operasi.md)",
     "the anchor log is already {size}; above {limit} it is no longer read and all tracing and issuing are refused. "
     "Continue now in a new segment with tapak jangkar rotasi BERKAS_BARU (see docs/operasi.md)"),
    ("baris ke-{n} log jangkar tidak dapat dibaca dan diabaikan", "line {n} of the anchor log cannot be read and is ignored"),
    ("baris pertama log jangkar yang terbaca (baris ke-{n}) bukan baris awal: log dipotong dari depan atau disunting",
     "the first readable line of the anchor log (line {n}) is not a start line: the log was cut from the front or edited"),
    ("log jangkar memuat lebih dari satu baris awal (baris ke-{n})", "the anchor log holds more than one start line (line {n})"),
    ("baris ke-{n} milik log jangkar lain (id berbeda dengan baris awal)",
     "line {n} belongs to another anchor log (its id differs from the start line)"),
    ("tanda tangan baris ke-{n} log jangkar tidak sah untuk kunci publik registri (baris dipalsukan atau diubah)",
     "the signature of anchor log line {n} is not valid for the registry public key (the line was forged or changed)"),
    ("baris pengakuan ke-{n} log jangkar tidak cocok dengan entri registri #{m}",
     "acknowledgement line {n} of the anchor log does not match registry entry #{m}"),
    ("log jangkar mencatat entri {span} ({kinds}) yang tidak ada lagi di registri; {head:t}: {why:t}",
     "the anchor log records entries {span} ({kinds}) that are no longer in the registry; {head}: {why}"),
    ("registri kini berakhir di entri #{n}", "the registry now ends at entry #{n}"),
    ("entri {span} di registri berbeda dari log jangkar: entri itu diganti entri lain (ujung rantai dihapus lalu "
     "ditambah entri baru sehingga rantai bercabang, atau registri ditulis ulang)",
     "entries {span} in the registry differ from the anchor log: they were replaced by other entries (the end of the "
     "chain was deleted and new entries added so the chain forks, or the registry was rewritten)"),
    ("isi entri {span} diubah: hash yang tersimpan masih sama dengan log jangkar, tetapi tidak cocok lagi dengan isinya",
     "the payload of entries {span} was changed: the stored hash still matches the anchor log, but no longer matches "
     "the payload"),
    ("baris log jangkar untuk entri {span} menyebut jenis atau waktu yang berbeda dari registri (log atau registri "
     "disunting)",
     "the anchor log lines for entries {span} name a different kind or time than the registry (the log or the "
     "registry was edited)"),
    ("rantai registri rusak di entri #{n} ({why:t}), di dalam bagian yang dijangkarkan log jangkar (sampai entri #{m})",
     "the registry chain is broken at entry #{n} ({why}), inside the part the anchor log anchors (up to entry #{m})"),
    ("log jangkar berada di dalam {f}, bersama registri atau kunci; siapa pun yang dapat menyunting registri "
     "kemungkinan juga dapat menyunting log ini, jadi log ini tidak melindungi dari penghapusan. Pindahkan ke akun lain, "
     "media tulis-sekali, atau mesin lain (lihat docs/operasi.md)",
     "the anchor log is inside {f}, with the registry or the keys; anyone who can edit the registry can probably edit "
     "this log too, so it does not protect against deletion. Move it to another account, write-once media, or another "
     "machine (see docs/operasi.md)"),
    ("log jangkar {f} tidak cocok dengan registri: {problems:l}. Entri yang pernah tercatat hilang atau berubah, "
     "misalnya entri pelacakan yang dihapus dari ujung registri, sehingga nomor pelacakan dan jatah eps tidak dapat "
     "dipastikan. Periksa dengan tapak verify. {more:t}",
     "the anchor log {f} does not match the registry: {problems}. Entries once recorded are gone or changed, for "
     "example trace entries deleted from the end of the registry, so the trace numbers and eps shares cannot be "
     "established. Check with tapak verify. {more}"),

    # canary log (canary_dns/store.py)
    ("pemicu {which} hilang (berkas pernah disunting di luar TAPAK)", "trigger {which} is missing (the file was edited outside TAPAK)"),
    ("pemicu {which} telah diubah (berkas pernah disunting di luar TAPAK)", "trigger {which} was changed (the file was edited outside TAPAK)"),
    ("nomor urut melompat: diharapkan #{a}, ditemukan #{b} (catatan dihapus atau disisipkan)",
     "sequence number jumps: expected #{a}, found #{b} (records deleted or inserted)"),
    ("catatan #{n}: prev_hash tidak sama dengan hash catatan sebelumnya", "record #{n}: prev_hash differs from the previous record\u2019s hash"),
    ("catatan #{n}: hash tidak cocok dengan isinya (isi diubah)", "record #{n}: the hash does not match the payload (payload changed)"),
    ("berkas catatan kanari tidak ditemukan: {f}", "canary record file not found: {f}"),
    ("berkas tidak dapat dibaca sebagai basis data SQLite ({why})", "the file cannot be read as an SQLite database ({why})"),
    ("catatan #{n} yang dijangkarkan tidak ada lagi (ujung rantai dipotong atau catatan dihapus)",
     "anchored record #{n} is gone (the end of the chain was cut or records deleted)"),
    ("hash catatan #{n} berbeda dari jangkar (rantai ditulis ulang)", "the hash of record #{n} differs from the anchor (the chain was rewritten)"),
    ("... dan {n} masalah lain", "... and {n} more problems"),
    ("{n} jangkar kanari di registri tidak sah (hash atau tanda tangan salah)", "{n} canary anchors in the registry are invalid (wrong hash or signature)"),
    ("catatan #{a} sampai #{b} belum dijangkarkan", "records #{a} to #{b} are not anchored yet"),

    # the local language model (llm/)
    ("server LLM lokal tidak dapat dihubungi di {url}", "the local LLM server at {url} cannot be reached"),
    ("server LLM lokal di {url} menolak permintaan (HTTP {code})", "the local LLM server at {url} refused the request (HTTP {code})"),
    ("server LLM lokal di {url} tidak menjawab dalam {s} detik (model terlalu lambat atau mesin sibuk); naikkan {var} "
     "atau pakai model yang lebih kecil",
     "the local LLM server at {url} did not answer within {s} seconds (the model is too slow or the machine is busy); "
     "raise {var} or use a smaller model"),
    ("berkas model GGUF tidak ditemukan: {f}", "GGUF model file not found: {f}"),
    ("{url} bukan server LLM yang dikenali (GET {path} tidak berisi daftar model); periksa TAPAK_LLM_URL",
     "{url} is not a recognised LLM server (GET {path} holds no model list); check TAPAK_LLM_URL"),

    # demo sandbox (web/demo_web.py)
    ("{f} bukan folder demo TAPAK; folder itu tidak disentuh", "{f} is not a TAPAK demo folder; it was left untouched"),
    ("cara bocor tidak dikenal: {m}", "unknown kind of leak: {m}"),
    ("{name} harus bilangan bulat positif (jumlah proses kerja paling banyak), bukan {v}",
     "{name} must be a positive whole number (the largest number of worker processes), not {v}"),
]

_PLACEHOLDER = re.compile(r"\{(\w+)(?::([tlcn]))?\}")


def _compile(template: str) -> tuple[re.Pattern[str], dict[str, str]]:
    """The regular expression of an Indonesian template and the flag of each placeholder."""
    regex, flags, pos = [], {}, 0
    for m in _PLACEHOLDER.finditer(template):
        regex.append(re.escape(template[pos:m.start()]))
        flags[m[1]] = m[2] or ""
        regex.append(rf"(?P<{m[1]}>[\d.,]+)" if m[2] == "n" else rf"(?P<{m[1]}>.+?)")
        pos = m.end()
    regex.append(re.escape(template[pos:]))
    return re.compile("".join(regex), re.S), flags


PATTERNS: list[tuple[re.Pattern[str], dict[str, str], str]] = [(*_compile(id_), en) for id_, en in RULES]
