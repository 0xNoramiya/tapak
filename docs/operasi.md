# Menjalankan TAPAK

[Kembali ke README](../README.md) · [Cara kerja](cara-kerja.md) · [Keamanan dan batasan](keamanan.md)

## Prasyarat

Python 3.11 atau lebih baru, `uv` (atau pip), Tesseract dengan bahasa Indonesia, poppler-utils, dan pango (untuk WeasyPrint). Di Ubuntu:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-ind poppler-utils libpango-1.0-0 libharfbuzz-subset0
make setup          # memasang dependensi (sekali, perlu jaringan)
make demo           # skenario lengkap tanpa interaksi
make test           # seluruh pengujian
make simulate       # angka simulasi Tardos
make photos bench   # kumpulan foto sintetis lalu uji regresi dekoder
make web            # antarmuka web di http://127.0.0.1:8000
make figures        # grafik README dibuat ulang dari kode dan data (perlu: uv pip install -e ".[figures]")
```

Setelah `make setup`, semuanya berjalan luring. Tangkapan layar antarmuka di README dibuat terpisah dengan `docs/figures/shoot_ui.py` (perlu Playwright dan Chromium). Tanpa `TAPAK_FIG_FONTS` (Inter dan JetBrains Mono), grafik memakai DejaVu.

## Baris perintah

```bash
tapak keys init                                  # rahasia kode + kunci tanda tangan registri
tapak issue samples/nota_dinas.pdf samples/recipients.csv --canary-domain kanari.satuan.mil
tapak docs                                       # daftar dokumen terbitan
tapak trace foto_bocor.jpg --doc <hash> --report berita_acara.pdf
tapak trace foto_hal1.jpg foto_hal2.jpg --doc <hash>      # beberapa bukti satu kebocoran, digabung
tapak trace foto_bocor.jpg --master induk.pdf --manifest manifest.json --pelacakan-ke 2   # ulangi pelacakan ke-2 (perintah di berita acara)
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

Port 53 harus bebas di komputer pendengar. Di banyak distro Linux, `systemd-resolved` sudah memakai 127.0.0.53:53. Ikat pendengar ke alamat publik, atau jalankan di port lain lalu teruskan port 53 ke sana seperti di Docker.

Pihak ketiga cukup memegang berkas registri dan kunci publik:

```bash
tapak-verify-registry data/registry.db --public-key keys/registry_signing.pub
```

## Antarmuka web

Antarmuka web punya dua halaman utama:

* **Terbitkan**: unggah PDF dan CSV penerima, lihat rencana penandaan dan gerbang visual, pilih kalimat aman, lalu tinjau setiap varian LLM. Tombol terbit terkunci sampai semua varian disetujui atau ditolak. Setelah terbit, unduh ZIP.
* **Lacak**: pilih dokumen, lalu unggah foto, tangkapan layar, PDF, atau DOCX, atau tempel teks. Beberapa berkas dari kebocoran yang sama (misalnya foto tiap halaman) boleh dipilih sekaligus dan digabung dalam satu pelacakan. Hasilnya menampilkan putusan, skor, ambang, peluang tuduhan salah, kanal yang sepakat, status registri, peringatan kanari, dan tombol unduh berita acara.

Halaman PDF tanpa lapisan teks yang cocok (hasil pindai) atau dengan lapisan teks OCR tak terlihat dibaca sebagai gambar. Halaman yang diperkecil, digeser, atau dicetak ke ukuran kertas lain lebih dulu dinormalkan ke bingkai dokumen induk (skala dan pergeseran per halaman). Setelah itu, kanal geser dibaca dari teksnya dan pola latar dari gambarnya.

Halaman **Registri** menampilkan status rantai, kunci publik, akar Merkle, dan peringatan kanari.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="img/ui-terbitkan-dark.png">
  <img alt="Langkah rencana penandaan di halaman Terbitkan: jumlah halaman, panjang kode, ambang, dan kapasitas setiap kanal" src="img/ui-terbitkan-light.png" width="100%">
</picture>

## Docker

```bash
.venv/bin/tapak keys init                        # kunci di ./keys (dipasang ke kontainer app saja)
mkdir -p data/kanari data/kanari-izin && sudo chown -R 10001 data keys
docker compose up --build -d                     # app (127.0.0.1:8000) dan canary-dns (port 53 -> 5353)
```

Kontainer `canary-dns` hanya melihat `data/kanari` (log kejadiannya, dapat ditulis) dan `data/kanari-izin` (daftar digest token, hanya-baca). Di belakang proksi terbalik, tambahkan nama publik aplikasi ke `TAPAK_ALLOWED_HOSTS` (misalnya `127.0.0.1,localhost,tapak.satuan.mil`; bentuk `*.domain` didukung). Di Docker, tulis variabel ini di bagian `environment` layanan `app` pada `docker-compose.yml`, karena compose hanya meneruskan `TAPAK_CANARY_DOMAIN` dan `TAPAK_LLM` dari lingkungan host. Tanpa itu, aplikasi menolak header Host dan Origin asing.

Kunci tanda tangan registri tidak harus ada di server. Tanpa kunci itu, entri baru dicatat tanpa tanda tangan, dan eselon atas menandatanganinya dengan `tapak registry sign --key ...` di komputernya sendiri.

## Kunci dan konfigurasi

| Berkas | Isi | Pemegang |
|---|---|---|
| `keys/code_secret.key` | rahasia 32 byte; menurunkan vektor bias, kata kode, dan rencana penandaan | operator TAPAK |
| `keys/registry_signing.key` | benih Ed25519 penanda tangan registri | dapat dipegang eselon atas, terpisah dari konfigurasi aplikasi |
| `keys/registry_signing.pub` | kunci publik verifikasi | siapa saja |

Variabel lingkungan:

| Variabel | Fungsi |
|---|---|
| `TAPAK_DATA`, `TAPAK_KEY_DIR` | lokasi data dan kunci |
| `TAPAK_CANARY_DOMAIN` | domain kanari bawaan |
| `TAPAK_LLM` | `mock` atau `llamacpp` |
| `TAPAK_LLM_MODEL` | berkas GGUF 7 sampai 8B yang mampu berbahasa Indonesia |
| `TAPAK_LLM_URL` | server llama.cpp lokal; alamat selain loopback ditolak |
| `TAPAK_ALLOWED_HOSTS` | nama host yang dilayani aplikasi web; bawaan `127.0.0.1,localhost` |
| `TAPAK_SIGNING_KEY`, `TAPAK_PUBLIC_KEY` | lokasi kunci tanda tangan dan kunci publik registri; bawaan di `TAPAK_KEY_DIR` |
| `TAPAK_CANARY_NS_IP` | alamat IPv4 publik pendengar kanari untuk `ns1.<domain>`, sama dengan glue di registrar |
| `TAPAK_CANARY_ANSWER_IP` | (docker-compose) alamat IPv4 jawaban untuk nama kanari; bawaan `127.0.0.1` |

## Pengujian

`make test` menjalankan seluruh suite pytest:
- kode Tardos dan dekoder, dengan uji untuk setiap fungsi publik;
- penanda, kanal 3 lewat MuPDF dan poppler, ketidakterlihatan pada 600 dpi;
- foto dan tangkapan layar, kolusi, jalur "tidak cukup bukti";
- registri dan perusakannya, kanari DNS di bawah 5 detik, kanal semantik dengan salah ketik;
- DOCX, berita acara, antarmuka web end-to-end;
- aturan kebersihan repositori (sumber Python hanya ASCII, tanpa tanda pisah panjang).

Suite ini tidak memerlukan GPU, model LLM, atau jaringan. Uji foto ditandai `slow`, dan `make test-fast` melewatinya.
