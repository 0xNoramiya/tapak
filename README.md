# TAPAK: Tanda Atribusi Penerima Anti-Kolusi

Prototipe atribusi kebocoran dokumen rahasia untuk Kartika Cyber Hackathon 2026 (kategori Core Infra).

Setiap salinan PDF rahasia yang dibagikan diberi sidik per penerima yang tidak terlihat mata. Bila foto, tangkapan layar, berkas yang diteruskan, atau teks salinan itu bocor, dekoder forensik TAPAK menunjuk salinan sumbernya **beserta peluang tuduhan salahnya**, lalu menulis berita acara. Kodenya adalah kode Tardos yang tahan kolusi: dua atau tiga penerima yang membandingkan salinan tidak dapat menghapus sidik atau memfitnah orang lain. Seluruh pemrosesan berjalan di perangkat sendiri; tidak ada data yang dikirim ke awan.

Semua dokumen, satuan, nama, dan nomor di repositori ini **fiktif** dan setiap halaman contoh bertanda "CONTOH SINTETIS - BUKAN DOKUMEN ASLI".

## Ringkasan hasil

| Pengujian | Hasil |
|---|---|
| Simulasi kolusi Tardos, N=100, c=3, eps=1e-6, 1000 percobaan x 7 strategi | **0 tuduhan salah**, deteksi **100 %**, semua anggota koalisi tertangkap 100 % |
| Set foto sintetis (`make photos` + `make bench`): 32 foto 0 sampai 30 derajat dan 8 tangkapan layar, JPEG ganda gaya WhatsApp | **38 dari 40 benar**, 2 "tidak cukup bukti" (foto terlalu terang: pola latar hilang atau terlalu lemah), **0 tuduhan salah** |
| Foto 10 sampel sampai 30 derajat (uji M3) | 10 dari 10 benar |
| Halaman gabungan setengah atas salinan A dan setengah bawah salinan B | A dan B dituduh, tidak ada orang lain |
| Teks salinan disalin-tempel (MuPDF dan poppler) | kode utuh, salinan teridentifikasi |
| Teks diketik ulang dengan 5 % salah ketik (kanal semantik) | bit semantik pulih 20 dari 20 percobaan |
| Penerbitan 20 salinan dokumen 2 halaman | sekitar 4 sampai 5 detik |
| Kanari DNS setelah salinan dibuka | tercatat dalam sekitar 0,1 detik (syarat: di bawah 5 detik) |
| Registri: verifikasi hanya dengan kunci publik, setiap perubahan baris terdeteksi | lulus |
| `make demo` (skenario lengkap) | sekitar 15 detik |

## Cara kerja

Kode penerima yang sama ditanam di lima kanal. Kanal mana pun boleh rusak; dekoder menggabungkan apa yang tersisa.

| Kanal | Apa yang ditanam | Bertahan terhadap |
|---|---|---|
| 1. Geser kata dan baris | kelompok kata bergeser horizontal dan baris bergeser vertikal sebesar 0,05 mm; bit dikodekan secara *relatif* terhadap tetangga (kontrol, data, kontrol) sehingga sisa distorsi perspektif saling meniadakan | cetak, foto, tangkapan layar |
| 2. Pola latar | pola acak berfrekuensi rendah +/-2 tingkat abu-abu (sel 2 mm), setiap posisi kode menguasai 8 sel yang tersebar; didekode secara buta per bit | layar, tangkapan layar, foto layar |
| 3. Karakter tak terlihat | sepasang simbol lebar-nol sebelum dan sesudah kata (2 bit per simbol) serta huruf kembar Kiril pada kata huruf kecil | salin-tempel, berkas diteruskan |
| 4. Varian semantik | parafrasa kalimat pembuka, penutup, dan tembusan oleh LLM lokal, disetujui manusia | pengetikan ulang |
| 5. Token kanari | satu subdomain unik per salinan di bawah domain kanari; pendengar DNS mencatat siapa yang membukanya | berkas dibuka di luar jaringan satuan |

**Kode Tardos.** Setiap dokumen memiliki vektor bias p (distribusi arcsine dengan batas t = 1/(300c)) dan setiap salinan memiliki kata kode biner x_j. Panjang kode m = K c^2 ln(1/eps1) dengan eps1 = eps/N (batas gabungan untuk N penerima), K = 2 pi^2 (bawaan) atau 100 (konservatif). Skor tuduhan memakai skor simetris Skoric dkk.: S_j = jumlah w_i U(y_i, x_ji, p_i).

**Ambang ditetapkan sebelum skor dihitung.** Aturan ambang ditetapkan saat penerbitan dan dicatat di registri (bersama nilai Z untuk pembacaan penuh). Nilai Z untuk sebuah bukti dihitung setelah dekode dari batas Chernoff yang ketat terhadap vektor bias yang sebenarnya dan bobot dekoder (posisi yang tidak terbaca tidak dihitung), dengan bit bocor terburuk di setiap posisi. Perhitungannya sama sekali tidak melihat kode penerima mana pun, dicatat dengan cap waktu di hasil dan berita acara, baru kemudian skor dihitung. Jaminan tuduhan salah karenanya **tidak bergantung pada konstanta K maupun pendekatan Gauss**; K hanya memengaruhi tingkat deteksi, yang diukur dengan simulasi.

**Fusi bukti.** Setiap kanal menghasilkan rasio log-kemungkinan (LLR) per posisi kode tanpa pernah melihat kode penerima. LLR dijumlahkan, keputusan y_i = tanda LLR, bobot w_i = tanh(|LLR|/2). Akusasi dijalankan pada hasil fusi dan pada setiap kanal fisik secara terpisah, sehingga laporan menyebut berapa kanal yang sepakat secara independen. Kanal yang saling bertentangan dilaporkan sebagai kemungkinan manipulasi.

**Aturan keluaran.** Nama hanya muncul bersama skor, ambang, dan peluang tuduhan salahnya. Bila tidak ada salinan yang melewati ambang, keluarannya "tidak cukup bukti" dan tidak ada nama yang disebut.

## Arsitektur

```
            +---------------- Terbitkan ----------------+          +------------------ Lacak ------------------+
 PDF induk  |  layout   rencana penyematan (kunci)      |  salinan | foto / tangkapan layar / PDF / DOCX / teks |
 + penerima |  model -> geser, latar, teks, semantik,   |--------->|  rectify (kontur, SIFT, Tesseract) + ECC   |
            |           kanari -> render ulang + gerbang |          |  ch_shift  ch_background  ch_zerowidth      |
            |           visual -> 20 salinan PDF          |          |  ch_semantic  ch_docx                       |
            +----------------------+---------------------+          |        -> fuse (LLR) -> accuse (Chernoff) |
                                   |                                |        -> berita acara (WeasyPrint)        |
                                   v                                +--------------------+-----------------------+
           registri SQLite tambah-saja: rantai SHA-256, tanda tangan Ed25519,           |
           akar Merkle harian; hanya hash, id, dan komitmen kode   <--------------------+  verifikasi silang
                                   ^
                                   |  peristiwa kanari (rantai hash sendiri)
                       pendengar DNS otoritatif (dnslib)
```

```
tapak/
  tardos/       params, code (SHAKE-256), accuse (skor simetris, ambang Chernoff), attacks, simulate
  marker/       layout, master (font), plan, pdf_shift, background, pdf_zerowidth, semantic, canary,
                docx_marker, render (gambar ulang + gerbang visual), issue (paralel)
  decoder/      rectify, lines (Tesseract), ch_shift, ch_background, ch_zerowidth, ch_semantic, ch_docx,
                image, fuse, accuse, trace, report (berita acara)
  registry/     chain (rantai hash, trigger tambah-saja), signing (Ed25519), verify, merkle
  canary_dns/   server (dnslib), store (log berantai)
  llm/          provider (antarmuka), mock (deterministik), llamacpp (lokal, loopback saja)
  learned_wm/   kerangka tanda air terlatih (opsional, belum dilatih)
  web/          FastAPI + HTMX, antarmuka berbahasa Indonesia
  photos.py     simulator degradasi foto dan tangkapan layar
  service.py    alur bersama CLI, web, dan demo
  cli.py        tapak issue | trace | simulate | verify | demo | ...
samples/        templat nota dinas dan surat telegram fiktif, PDF contoh, daftar penerima
tests/          pytest (tanpa GPU, tanpa model LLM, tanpa jaringan)
docs/results/   keluaran simulasi dan benchmark
```

## Menjalankan

Prasyarat: Python 3.11 atau lebih baru, `uv` (atau pip), Tesseract dengan bahasa Indonesia, poppler-utils, pango (untuk WeasyPrint). Di Ubuntu:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-ind poppler-utils libpango-1.0-0 libharfbuzz-subset0
make setup          # memasang dependensi (sekali, perlu jaringan)
make demo           # skenario lengkap tanpa interaksi
make test           # seluruh pengujian
make simulate       # angka simulasi Tardos
make photos bench   # set foto sintetis lalu uji regresi dekoder
make web            # antarmuka web di http://127.0.0.1:8000
```

Setelah `make setup`, semuanya berjalan luring.

### Baris perintah

```bash
tapak keys init                                  # rahasia kode + kunci tanda tangan registri
tapak issue samples/nota_dinas.pdf samples/recipients.csv --canary-domain kanari.satuan.mil
tapak docs                                       # daftar dokumen terbitan
tapak trace foto_bocor.jpg --doc <hash> --report berita_acara.pdf
tapak trace foto_hal1.jpg foto_hal2.jpg --doc <hash>      # beberapa bukti satu kebocoran, digabung
tapak verify                                     # verifikasi registri dengan kunci publik saja
tapak verify --jangkar 63:<hash>                 # juga mendeteksi entri yang dihapus setelah jangkar itu
tapak registry export-merkle                     # akar Merkle harian
tapak semantic suggest dok.pdf -o varian.json    # usulan varian oleh LLM lokal
tapak semantic approve varian.json --unit u0 --variant 2   # keputusan manusia
tapak issue dok.pdf penerima.csv --semantic varian.json    # ditolak jika masih ada varian menunggu
tapak simulate --n 100 --c 3 --eps 1e-6 --trials 1000
tapak simulate --table
tapak canary-dns --domain kanari.satuan.mil --port 53   # log di data/kanari/, daftar izin di data/kanari-izin/
tapak kanari-izin                                # tulis ulang daftar izin token dari semua penerbitan
```

Port 53 harus bebas di mesin pendengar (pada banyak distro Linux, `systemd-resolved` memegang 127.0.0.53:53; pendengar tetap dapat diikat ke alamat publik, atau jalankan di port lain lalu teruskan port 53 ke sana seperti di Docker).

Pihak ketiga cukup memegang berkas registri dan kunci publik:

```bash
tapak-verify-registry data/registry.db --public-key keys/registry_signing.pub
```

### Antarmuka web

Dua pintu masuk berbahasa Indonesia:

* **Terbitkan**: unggah PDF dan CSV penerima, lihat rencana penandaan dan gerbang visual, pilih kalimat aman, tinjau setiap varian LLM (tombol terbit terkunci sampai semua varian disetujui atau ditolak), terbitkan, unduh ZIP.
* **Lacak**: pilih dokumen, unggah foto, tangkapan layar, PDF, DOCX, atau tempel teks. Halaman PDF tanpa lapisan teks yang cocok (hasil pindai) atau dengan lapisan teks OCR tak terlihat dibaca sebagai gambar. Halaman yang dicetak diperkecil, digeser, atau ke ukuran kertas lain dinormalkan dulu ke bingkai dokumen induk (skala dan pergeseran per halaman), lalu membawa geser dari teksnya dan pola latar dari gambarnya. Hasil menampilkan putusan, skor, ambang, peluang tuduhan salah, kanal yang sepakat, status registri, peringatan kanari, dan tombol unduh berita acara.

Halaman **Registri** menampilkan status rantai, kunci publik, akar Merkle, dan peringatan kanari.

### Docker

```bash
.venv/bin/tapak keys init                        # kunci di ./keys (dipasang ke kontainer app saja)
mkdir -p data/kanari data/kanari-izin && sudo chown -R 10001 data keys
docker compose up --build -d                     # app (127.0.0.1:8000) dan canary-dns (port 53 -> 5353)
```

Kontainer `canary-dns` hanya melihat `data/kanari` (log kejadiannya, dapat ditulis) dan `data/kanari-izin` (daftar digest token, hanya-baca). Di belakang proksi terbalik, tambahkan nama publik aplikasi ke `TAPAK_ALLOWED_HOSTS` (misalnya `127.0.0.1,localhost,tapak.satuan.mil`; bentuk `*.domain` didukung); tanpa itu aplikasi menolak header Host dan Origin asing.

Kunci tanda tangan registri boleh tidak dipasang di server; entri baru lalu dicatat tanpa tanda tangan dan eselon atas menandatanganinya dengan `tapak registry sign --key ...` di mesinnya sendiri.

### Kunci dan konfigurasi

| Berkas | Isi | Pemegang |
|---|---|---|
| `keys/code_secret.key` | rahasia 32 byte; menurunkan vektor bias, kata kode, dan rencana penyematan | operator TAPAK |
| `keys/registry_signing.key` | benih Ed25519 penanda tangan registri | dapat dipegang eselon atas, terpisah dari konfigurasi aplikasi |
| `keys/registry_signing.pub` | kunci publik verifikasi | siapa saja |

Konfigurasi lain lewat variabel lingkungan: `TAPAK_DATA`, `TAPAK_KEY_DIR`, `TAPAK_CANARY_DOMAIN`, `TAPAK_LLM` (`mock` atau `llamacpp`), `TAPAK_LLM_MODEL` (berkas GGUF 7 sampai 8B yang mampu berbahasa Indonesia), `TAPAK_LLM_URL` (server llama.cpp lokal; alamat selain loopback ditolak), `TAPAK_ALLOWED_HOSTS` (nama host yang dilayani aplikasi web; bawaan `127.0.0.1,localhost`).

## Angka simulasi

Perintah: `tapak simulate --n 100 --c 3 --eps 1e-6 --trials 1000` (m = 3273 bit).

| Strategi kolusi | Tuduhan salah | Deteksi (minimal 1 anggota) | Semua anggota tertangkap | Z rata-rata | Skor koalisi tertinggi |
|---|---|---|---|---|---|
| mayoritas | 0 / 1000 | 1,000 | 1,000 | 372,5 | 772,6 |
| minoritas | 0 / 1000 | 1,000 | 1,000 | 372,5 | 768,1 |
| campuran acak | 0 / 1000 | 1,000 | 1,000 | 372,5 | 773,3 |
| lempar koin | 0 / 1000 | 1,000 | 1,000 | 372,5 | 769,7 |
| selalu 1 | 0 / 1000 | 1,000 | 1,000 | 372,5 | 770,9 |
| selalu 0 | 0 / 1000 | 1,000 | 1,000 | 372,5 | 770,6 |
| hapus (rata-rata dua salinan) | 0 / 1000 | 1,000 | 1,000 | 306,5 | 722,8 |

Skor inosen tertinggi di seluruh percobaan adalah 72 % dari ambang. Nol tuduhan salah dalam 1000 percobaan hanya membuktikan lajunya di bawah sekitar 3 x 10^-3, sehingga batasnya juga diuji pada tingkat yang dapat diukur: pada target 10^-2 laju empirisnya 6,8 x 10^-4 dan pada target 10^-3 lajunya 3,3 x 10^-5 (dari 582.000 skor inosen). Batas Chernoff terbukti konservatif.

Uji tambahan (berkas lengkap di `docs/results/`):

| Skenario | Tuduhan salah | Deteksi | Semua tertangkap |
|---|---|---|---|
| N=20, c=3 (m=2987) | 0 | 100 % | 100 % |
| N=100, c=3, kanal berderau: 5 % bit salah, 35 % terhapus | 0 | 100 % | 98 sampai 100 % |
| N=100, kode untuk c=3 diserang **5** orang (di luar rancangan) | 0 | 100 % | 42 sampai 49 % |

Tabel parameter (eps = 10^-6 untuk seluruh daftar, `tapak simulate --table`):

| N | c | eps1 | m (K=2 pi^2) | m (K=100) | Z Chernoff | Z Gauss | rata-rata skor kolusi per anggota |
|---|---|---|---|---|---|---|---|
| 20 | 2 / 3 / 5 | 5e-8 | 1328 / 2987 / 8297 | 6725 / 15131 / 42029 | 233 / 340 / 552 | 194 / 291 / 485 | 423 / 634 / 1056 |
| 50 | 2 / 3 / 5 | 2e-8 | 1400 / 3150 / 8749 | 7092 / 15955 / 44319 | 246 / 359 / 582 | 205 / 308 / 514 | 446 / 668 / 1114 |
| 100 | 2 / 3 / 5 | 1e-8 | 1455 / 3273 / 9091 | 7369 / 16579 / 46052 | 256 / 373 / 605 | 214 / 321 / 535 | 463 / 695 / 1158 |
| 500 | 2 / 3 / 5 | 2e-9 | 1582 / 3559 / 9885 | 8013 / 18028 / 50076 | 278 / 405 / 658 | 234 / 351 / 585 | 504 / 755 / 1259 |

## Keputusan desain yang menyimpang dari spesifikasi awal

| Spesifikasi | Yang dibangun | Alasan |
|---|---|---|
| Kode penuh ditanam di setiap kanal | kanal teks membawa seluruh m bit; setiap halaman membawa irisannya sendiri di kanal fisik; akusasi hanya atas posisi yang terbaca dengan ambang ketat untuk himpunan itu | c=3, eps=10^-6 memerlukan sekitar 3000 bit, sedangkan geser kata dan baris hanya memuat sekitar 90 bit per halaman. Skala c^2 ln(1/eps) adalah batas bawah untuk kode tahan kolusi apa pun |
| Geser 0,01 sampai 0,03 mm | 0,05 mm (dapat diatur, maksimum 0,05 mm) | 0,01 sampai 0,03 mm hanya 0,1 sampai 0,3 piksel pada foto ponsel satu halaman A4; tidak terukur setelah JPEG |
| "Selisih piksel tak terlihat" | didefinisikan secara geometris: di antara dua salinan mana pun, tidak ada glif yang bergeser lebih dari 0,1 mm per sumbu (1 menit busur pada jarak baca 35 cm); diuji pada 600 dpi bahwa perbedaan piksel hanya ada di kotak kata yang digeser (di luar itu hanya pola latar, maksimum 4 tingkat abu-abu) dan pusat tinta bergeser sesuai rencana | tanda geometris mengubah posisi tepi, bukan kontras; ambang tingkat abu-abu tidak bermakna untuk itu |
| Pola latar didekode dengan korelasi terhadap kandidat | korelasi buta per bit (spread spectrum) | korelasi terhadap kandidat menggunakan kode penerima dan merusak jaminan tuduhan salah Tardos |
| Registri menyimpan kode | registri menyimpan komitmen (`code_digest`); kode diturunkan ulang dari rahasia kode | siapa pun yang dapat membaca kode dapat memfitnah penerima |
| Kanari DOCX lewat referensi font eksternal | relasi gambar eksternal | Word tidak mengambil font eksternal |
| Banyak simbol lebar-nol di akhir kata | paling banyak dua simbol per posisi (sebelum dan sesudah kata), dari alfabet berbeda | MuPDF dan poppler membuang glif identik yang ditumpuk di posisi yang sama (dianggap tebal palsu) |
| Ambang Z ditetapkan sebelum analisis | aturan ambang ditetapkan saat penerbitan; nilai Z dihitung setelah dekode dari posisi yang benar-benar terbaca, sebelum skor dihitung | kanal yang rusak menghapus posisi; ambang yang tetap untuk pembacaan penuh akan terlalu ketat untuk bukti parsial. Aturannya tetap dan tidak pernah melihat kode penerima, sehingga tidak dapat disesuaikan setelah melihat hasil |
| Konstanta "Skoric 2006, 2 pi^2" | dipertahankan sebagai bawaan, atribusi dikoreksi | 2 pi^2 berasal dari Skoric, Vladimirova, Celik, dan Talstra untuk skor asimetris (pendekatan Gauss). Dengan skor simetris konstanta asimtotiknya pi^2/2, jadi ada margin sekitar 4 kali; untuk c kecil ini bukan batas yang terbukti, tetapi jaminan tuduhan salah TAPAK tetap ketat karena berasal dari ambang Chernoff |

### Format registri (untuk auditor)

* Setiap entri: `entry_hash = SHA-256(JSON kanonis {seq, kind, payload, prev_hash, created_at})`, JSON kanonis = kunci terurut, tanpa spasi, UTF-8. `prev_hash` entri pertama adalah 64 angka nol. Tanda tangan Ed25519 dibuat atas 32 byte `entry_hash`.
* Jenis entri `document` (parameter kode, kanal, ringkasan rencana, aturan dan nilai ambang) dan `copy` (`doc_hash`, `recipient_id`, `copy_id`, `seq`, `code_digest`, `channels_used`, `semantic_variant_ids`, `issued_at`, `issuer`, `file_sha256`, `canary_token` dalam bentuk `sha256:` hash, bukan token aslinya, dan `recipient_mac`: HMAC-SHA256 dengan rahasia kode atas id, nama, jabatan, dan satuan penerima, sehingga nama terikat ke entri bertanda tangan tanpa tersimpan di registri dan tidak dapat ditebak dari daftar personel).
* Akar Merkle harian: daun = 32 byte mentah `entry_hash`, simpul = SHA-256(kiri || kanan), simpul ganjil digandakan, satu daun adalah akarnya sendiri. Berkas `merkle-YYYY-MM-DD.txt` hanya untuk hari UTC yang sudah selesai; hari berjalan ditulis sebagai `.partial.txt` (sementara). Setiap berkas memuat hash berkas hari sebelumnya, sehingga penghapusan entri di ujung rantai pun terdeteksi bila berkas akar disimpan di luar sistem.
* Berkas kunci tanda tangan berisi `ed25519-seed:<64 hex>`; kunci publik berupa 64 hex.
* Log peristiwa kanari ada di berkas terpisah `data/kanari/kanari.db` (tabel `canary_events` dengan rantai hash sendiri), bukan di registri; `python -m tapak.canary_dns --anchor` menambatkan ujungnya ke registri bertanda tangan.

## Keamanan dan minimisasi data

* Registri hanya berisi hash dokumen, hash nama berkas (bukan namanya), parameter kode, id penerima, id salinan, komitmen kode, nama kanal, id varian, waktu, penerbit, hash berkas salinan, digest token kanari, dan komitmen berkunci identitas penerima. Tidak ada teks dokumen, gambar, maupun nama penerima.
* Nama penerima hanya ada di catatan penerbitan lokal (`manifest.json`). Sebelum dekode dan sebelum menyebut nama, pelacakan memverifikasi rantai registri, mencocokkan parameter kode dokumen (c, eps, N, konstanta, kanal, ambang penuh) dengan entri dokumen, dan mencocokkan setiap salinan (id penerima, nomor, komitmen kode, hash berkas, komitmen nama, jabatan, satuan; tepat satu entri per salinan) dengan registri. Bila kunci publik ada tetapi dokumen tidak ditemukan di registri (berkas hilang atau terpotong, atau dokumen diterbitkan dengan `--no-registry` di instalasi yang memiliki kunci), bila rantai gagal diverifikasi, atau bila ada yang berbeda, pelacakan berhenti tanpa menyebut nama. Mode lepas `tapak trace ... --master --manifest` (perintah ulang di berita acara) tidak memeriksa registri, menyatakannya di keluaran, dan tidak membuat berita acara. Entri yang belum bertanda tangan disebut terang-terangan di hasil, CLI, dan berita acara karena belum terlindungi dari pemalsuan.
* Teks varian semantik adalah isi dokumen; disimpan di folder dokumen (`varian.json`) bersama PDF induk, dan registri hanya menyimpan hash-nya.
* `semantic_variant_ids` (misalnya `u0:v2`) dicatat di registri sesuai spesifikasi. Konsekuensinya: pembaca registri dapat melihat salinan mana yang menerima varian sama, yang setara dengan beberapa bit kode (4 dari sekitar 3000 posisi pada contoh). Registri dipegang satuan penerbit dan eselon atas, bukan oleh penerima; bila ini dianggap terlalu banyak, kolom itu dapat dikosongkan karena id varian dapat dihitung ulang dari rahasia kode saat pelacakan.
* Kode setiap penerima diturunkan dari rahasia kode dengan SHAKE-256 (dapat dibangkitkan ulang bit demi bit bertahun-tahun kemudian, tidak bergantung versi numpy) dan diperiksa terhadap komitmen sebelum pelacakan.
* Kunci tanda tangan registri tidak pernah dibuat diam-diam: hanya `tapak keys init` yang membuatnya. Tanpa kunci, entri dicatat tanpa tanda tangan, laporan menyebutnya terang-terangan, dan pemegang kunci menandatanganinya kemudian.
* Tabel registri dijaga trigger tambah-saja; perubahan yang melewati trigger tetap terdeteksi karena rantai hash dan tanda tangan.
* Pendengar DNS kanari (satu-satunya bagian yang menghadap internet) memakai basis data sendiri di `data/kanari/` dan hanya mencatat token yang benar-benar diterbitkan (daftar digest di `data/kanari-izin/`), sehingga nama karangan tidak dapat membengkakkan log. Daftar itu disusun ulang dari catatan penerbitan dan ditulis dengan nama sementara acak lalu diganti namanya, tanpa pernah membaca atau mengikuti tautan di folder yang dapat ditulis pendengar; aplikasi membaca `kanari.db` lewat satu deskriptor tanpa mengikuti tautan dan tanpa memblokir (berkas biasa saja, ukuran dibatasi), lalu memuatnya ke memori, sehingga tautan atau FIFO yang ditanam tidak dapat membaca rahasia maupun menggantung aplikasi. Di Docker, kontainer pendengar hanya melihat kedua folder itu (folder daftar izin hanya-baca), berjalan sebagai pengguna non-root di port 5353, dan berada di jaringan terpisah dari aplikasi web.
* Aplikasi web tidak memiliki login: jalankan hanya di 127.0.0.1 (bawaan) atau di belakang proksi yang mengautentikasi. Aplikasi menolak header Host asing (melindungi dari DNS rebinding) dan permintaan POST dari asal lain, termasuk aplikasi lain di port localhost yang berbeda. Berkas data dibuat dengan izin hanya-pemilik (umask 077).
* Gambar bukti di atas 60 megapiksel ditolak setelah membaca kepala berkasnya saja, untuk semua format (PNG dan JPEG diperiksa TAPAK, format lain oleh batas piksel OpenCV `OPENCV_IO_MAX_IMAGE_PIXELS`). Halaman PDF yang dibaca sebagai gambar dibatasi per pelacakan (dua kali jumlah halaman induk, minimal 4, dan 60 megapiksel total; berhenti setelah dua halaman berturut-turut yang tidak cocok), dan hasil render bukti tidak disimpan di memori setelah permintaan. Antarmuka web menjalankan paling banyak dua pelacakan sekaligus.
* Satu-satunya lalu lintas keluar adalah pendengar DNS kanari yang menerima kueri. Antarmuka web memuat HTMX dan font dari server lokal.

## Batasan (jujur)

1. **Pengetikan ulang penuh dengan kalimat pembuka dan penutup ditulis ulang mengalahkan atribusi.** Kanal geser, latar, dan teks hilang; kanal semantik hanya membawa sedikit bit (contoh nota dinas: 2 kalimat, 4 bit). Teks ketikan ulang yang mempertahankan kalimat itu tetap dapat dibaca bitnya, tetapi 4 bit tidak cukup untuk menuduh pada eps = 10^-6, sehingga keluarannya "tidak cukup bukti".
2. **Kapasitas kanal semantik kecil**: sekitar 2 bit per kalimat aman yang disetujui, dan hanya kalimat yang tidak memuat angka, nama, waktu, koordinat, atau perintah.
3. **Kanal latar tidak bertahan dicetak**: printer menggambar tingkat abu-abu di atas sekitar 250 sebagai kertas polos. Foto kertas cetak hanya membawa kanal geser, sekitar 80 sampai 100 bit per halaman. Hasil terukur (foto 3000 px, eps = 10^-6, 6 salinan): **satu halaman tidak cukup** (0 dari 6, semuanya "tidak cukup bukti", walau salinan yang benar selalu berskor tertinggi); **dua halaman salinan yang sama digabung dalam satu pelacakan** (`tapak trace foto_hal1.jpg foto_hal2.jpg --doc ...`, atau pilih beberapa berkas di halaman Lacak) cukup untuk 5 dari 6, tanpa tuduhan salah. Ketahanan kolusi dari foto kertas cetak pada c = 3 tetap tidak tercapai; ketahanan kolusi dari foto bergantung pada kanal latar (layar dan tangkapan layar).
4. **Foto yang terlalu terang** (banyak piksel kertas jenuh 255) juga menghapus pola latar. Dekoder mendeteksinya dengan statistik umpan (sel yang sama dengan tanda acak independen): bila pola tidak lebih kuat dari derau, kanal latar tidak melaporkan apa pun (bukan derau) dan catatan hasil menyebutnya. Ujinya adalah uji z berpasangan atas selisih energi per bit (pola asli lawan umpan), dengan ambang tetap z = 3 (peluang sekitar 10^-3 menganggap foto tanpa pola sebagai berpola, berapa pun jumlah bit yang terlihat). Bila kanal geser saja tidak cukup, jawabannya "tidak cukup bukti", seperti pada 2 dari 40 gambar benchmark: satu tanpa pola sama sekali (51 % bit benar, setara tebakan), satu dengan pola lemah (65 % bit benar, z = 2,94, tepat di bawah ambang). Uji tanpa kode penerima memang jauh kurang peka daripada skor yang memakai kode, sehingga pola selemah itu tidak selalu terdeteksi; ambangnya tidak diturunkan setelah melihat hasil ini. Gerbang ini tidak memengaruhi jaminan tuduhan salah (bobot tidak pernah memakai kode penerima); gunanya mencegah derau mengencerkan bukti kanal geser.
5. **Geser baris rentan pada tangkapan layar beresolusi rendah** karena penampil PDF membulatkan garis dasar ke piksel. Dekoder menaksir derau per jenis dan otomatis memberi bobot kecil; geser kata (horizontal) tetap terbaca.
6. **Kanal teks tidak aman terhadap lawan yang paham**: simbol lebar-nol dan huruf Kiril dapat dibersihkan atau diubah. Mengubahnya tidak dapat memfitnah orang lain (lawan tidak tahu kode penerima lain), tetapi dapat menghapus bukti kanal itu. Pencarian frasa lintas kata di penampil PDF dapat gagal pada salinan bertanda; pencarian satu kata tetap berfungsi.
7. **Kanari bergantung pada penampil**: Adobe Reader menghubungi alamat aksi pembuka (dan menampilkan peringatan izin), Word mengambil gambar eksternal, sedangkan penampil peramban dan MuPDF tidak mengambil apa pun. Demo mensimulasikan pencarian DNS yang dilakukan penampil. Di dalam jaringan satuan, DNS internal harus menjawab zona kanari secara lokal agar penerima sah tidak memicu peringatan.
8. **Masukan harus PDF berlapis teks.** TAPAK menggambar ulang setiap glif; gerbang visual menolak penerbitan bila gambar ulang tanpa tanda tidak identik dengan aslinya (misalnya font tidak dapat dipakai ulang).
9. **Koalisi melebihi c** tetap tidak menimbulkan tuduhan salah, tetapi tidak semua anggotanya tertangkap (sekitar 45 % pada 5 orang melawan kode c=3).
10. **Foto sintetis bukan foto ponsel sungguhan.** Simulator mencakup perspektif, pencahayaan, bayangan, blur, derau, penajaman, dan JPEG ganda, tetapi tidak meniru pipeline kamera nyata (denoising agresif, HDR, moire layar). Pengujian dengan ponsel nyata belum dilakukan.
11. **Tanda air terlatih (StegaStamp) belum dilatih.** Kerangkanya ada di `tapak/learned_wm/` (model, degradasi, pelatihan, ekspor ONNX) dengan TODO; dekoder korelasi adalah jalur produksi.
12. **Konstanta 2 pi^2 dengan skor simetris belum terbukti untuk c kecil** (hanya asimtotik). Ini memengaruhi deteksi, bukan tuduhan salah; deteksi diukur dengan simulasi di atas. Konstanta 100 tersedia sebagai pilihan konservatif.

## Pengujian

`make test` menjalankan seluruh suite pytest: kode Tardos (setiap fungsi publik), penanda, dekoder (setiap fungsi publik), kanal 3 lewat MuPDF dan poppler, ketidakterlihatan pada 600 dpi, foto dan tangkapan layar, kolusi, jalur "tidak cukup bukti", registri dan perusakannya, kanari DNS di bawah 5 detik, kanal semantik dengan salah ketik, DOCX, berita acara, antarmuka web end-to-end, serta aturan kebersihan repositori (sumber Python hanya ASCII, tanpa tanda pisah panjang). Tidak memerlukan GPU, model LLM, atau jaringan; uji foto ditandai `slow` (`make test-fast` melewatinya).

## Referensi

1. G. Tardos. Optimal probabilistic fingerprint codes. Proc. 35th ACM STOC, 2003, hlm. 116-125. Versi jurnal: J. ACM 55(2), 2008.
2. B. Skoric, T. U. Vladimirova, M. Celik, J. C. Talstra. Tardos fingerprinting is better than we thought. IEEE Trans. Inf. Theory 54(8):3663-3676, 2008. arXiv:cs/0607131.
3. B. Skoric, S. Katzenbeisser, M. U. Celik. Symmetric Tardos fingerprinting codes for arbitrary alphabet sizes. Des. Codes Cryptogr. 46(2):137-166, 2008. IACR ePrint 2007/041.
4. T. Laarhoven, B. de Weger. Optimal symmetric Tardos traitor tracing schemes. Des. Codes Cryptogr. 71(1):83-103, 2014. arXiv:1107.3441.
5. J. T. Brassil, S. Low, N. F. Maxemchuk. Copyright protection for the electronic distribution of text documents. Proc. IEEE 87(7), 1999 (pergeseran baris dan kata).
6. M. Tancik, B. Mildenhall, R. Ng. StegaStamp: Invisible hyperlinks in physical photographs. CVPR 2020.

Font DejaVu dibundel dengan lisensi Bitstream Vera (lihat `tapak/assets/fonts/LICENSE-DejaVu.txt`); HTMX 1.9.12 (lisensi BSD) disertakan di `tapak/web/static/`.
