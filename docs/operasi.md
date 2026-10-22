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
make photos-cetak   # foto kertas cetak (printer disimulasikan); make bench melaporkannya terpisah
make bench-check    # ketiganya dari awal; hasilnya harus sama byte demi byte dengan docs/results
make web            # antarmuka web di http://127.0.0.1:8000
make figures        # grafik README dibuat ulang dari kode dan data (perlu: uv pip install -e ".[figures]")
```

Setelah `make setup`, semuanya berjalan luring. Tangkapan layar antarmuka di README dibuat terpisah dengan `docs/figures/shoot_ui.py` (perlu Playwright dan Chromium). Tanpa `TAPAK_FIG_FONTS` (Inter dan JetBrains Mono), grafik memakai DejaVu.

## Baris perintah

```bash
tapak keys init                                  # rahasia kode + kunci tanda tangan registri
tapak issue samples/nota_dinas.pdf samples/recipients.csv --canary-domain kanari.satuan.mil
tapak issue dok.pdf penerima.csv --latar cetak   # pola latar yang bertahan saat dicetak (lihat di bawah)
tapak docs                                       # daftar dokumen terbitan
tapak trace foto_bocor.jpg --doc <hash> --report berita_acara.pdf
tapak trace foto_hal1.jpg foto_hal2.jpg --doc <hash>      # beberapa bukti satu kebocoran, digabung
tapak trace foto_bocor.jpg --master induk.pdf --manifest manifest.json --pelacakan-ke 2 --bertahap bertahap-v1   # ulangi pelacakan ke-2 (perintah di berita acara)
tapak verify                                     # verifikasi registri dengan kunci publik saja
tapak verify --jangkar 63:<hash>                 # juga mendeteksi entri yang dihapus setelah jangkar itu
tapak --log-jangkar /mnt/jangkar/tapak.log jangkar mulai   # log jangkar eksternal (opsional, lihat di bawah)
tapak jangkar status                             # bandingkan log jangkar dengan registri, ukuran, dapat ditulis
tapak jangkar rotasi /mnt/jangkar/tapak-2.log    # teruskan log ke segmen baru sebelum batas ukurannya
tapak registry export-merkle                     # akar Merkle harian
tapak semantic suggest dok.pdf -o varian.json    # usulan varian oleh LLM lokal
tapak semantic approve varian.json --unit u0 --variant 2   # keputusan manusia
tapak issue dok.pdf penerima.csv --semantic varian.json    # ditolak jika masih ada varian menunggu
tapak leksikal scan dok.pdf -o leksikal.json     # titik pilihan kata (opsional), semua menunggu tinjauan
tapak leksikal show leksikal.json                # konteks, bentuk, status, jumlah bit
tapak leksikal review leksikal.json --interaktif # putuskan titik satu per satu
tapak issue dok.pdf penerima.csv --leksikal leksikal.json  # ditolak jika masih ada titik menunggu
tapak simulate --n 100 --c 3 --eps 1e-6 --trials 1000
tapak simulate --table
tapak simulate --n 100 --c 3 --coalition 5 --bertahap   # tuduhan satu tahap dan pelacakan bertahap pada bocoran yang sama
tapak canary-dns --domain kanari.satuan.mil --port 53   # log di data/kanari/, daftar izin di data/kanari-izin/
tapak kanari-izin                                # tulis ulang daftar izin token dari semua penerbitan
```

`--latar` memilih profil pola latar. `layar` (bawaan) tidak terlihat, tetapi hilang saat dokumen dicetak. `cetak` bertahan pada kertas cetak (diuji dengan printer simulasi), tetapi seluruh halaman tampak abu-abu muda dan teksturnya mungkin terlihat, sehingga TAPAK mencetak peringatan. Pakai `cetak` hanya untuk dokumen yang memang akan dicetak dan bila tampilan itu diterima ([cara kerja](cara-kerja.md#salinan-yang-dicetak)). Di antarmuka web pilihan yang sama ada di langkah pertama Terbitkan (Pola latar, bawaan Layar); bila Cetak dipilih, peringatan itu tampil di formulir, di rencana penandaan, dan di hasil penerbitan.

Pelacakan foto atau pindaian pertama untuk setiap halaman dan resolusi analisis merender templat induk tepat untuk kanal geser, sekitar 5 sampai 7 detik CPU per halaman penuh teks. `tapak web` menyimpannya di memori untuk pelacakan berikutnya, sedangkan setiap perintah `tapak trace` merendernya lagi.

Port 53 harus bebas di komputer pendengar. Di banyak distro Linux, `systemd-resolved` sudah memakai 127.0.0.53:53. Ikat pendengar ke alamat publik, atau jalankan di port lain lalu teruskan port 53 ke sana seperti di Docker.

Pihak ketiga cukup memegang berkas registri dan kunci publik:

```bash
tapak-verify-registry data/registry.db --public-key keys/registry_signing.pub
tapak-verify-registry data/registry.db --public-key keys/registry_signing.pub --log-jangkar tapak.log   # dengan log jangkar
```

Kode keluar: 0 utuh, 1 ada masalah, 3 utuh sejauh yang diperiksa tetapi registri memakai log jangkar yang tidak diberikan. Kode 3 berarti entri yang dihapus dari ujung rantai belum diperiksa; minta log jangkarnya (dan segmen lamanya, `--segmen-lama`, bila log pernah dirotasi).

## Log jangkar eksternal (opsional)

Tanpa log jangkar, entri pelacakan yang dihapus dari ujung registri dengan menyunting berkasnya di luar TAPAK hanya terungkap oleh jangkar di berita acara atau akar Merkle yang disimpan di luar sistem ([batasan 13](keamanan.md#batasan)). Log jangkar membuat penghapusan itu terdeteksi otomatis: setelah setiap entri registri tersimpan, TAPAK menambahkan satu baris (nomor, hash, jenis, waktu entri) ke berkas di penyimpanan terpisah, dan sebelum setiap pelacakan dan penerbitan membandingkan registri dengan berkas itu. Bila tidak diatur, perilaku TAPAK tidak berubah; hasil pelacakan hanya mendapat satu baris yang menyebut bahwa penghapusan itu belum terperiksa.

**Di mana menyimpannya.** Log hanya melindungi bila orang yang dapat menyunting `registry.db` tidak dapat menyunting log itu. Berkas di komputer dan akun yang sama tidak melindungi apa pun, dan TAPAK memperingatkan bila log berada di folder data atau kunci. Pilihan, dari yang paling sederhana:

* berkas di komputer yang sama yang diberi atribut tambah-saja oleh root (`sudo chattr +a`), sehingga akun TAPAK hanya dapat menambah baris. Ini melindungi dari pengguna biasa yang dapat menyunting registri, tetapi tidak dari root;
* media tulis-sekali (WORM) yang dipasang sebagai folder;
* folder di komputer kedua yang dipasang lewat sistem operasi (misalnya berbagi jaringan yang dikelola admin lain, tempat akun TAPAK hanya dapat menambah). TAPAK tidak menjalankan layanan jaringan untuk ini; penyimpanannya harus mendukung kunci berkas (`flock`).

**Memasang.**

```bash
sudo mkdir -p /mnt/jangkar && sudo chown tapak /mnt/jangkar     # atau pasang penyimpanan terpisahnya di sini
export TAPAK_ANCHOR_LOG=/mnt/jangkar/tapak.log                  # atau: tapak --log-jangkar /mnt/jangkar/tapak.log ...
tapak verify                                                     # registri harus utuh dulu
tapak jangkar mulai                                              # baris awal, lalu semua entri yang sudah ada
sudo chattr +a /mnt/jangkar/tapak.log                            # bila memakai atribut tambah-saja
tapak jangkar status                                             # cocok dengan registri sampai entri #N
```

TAPAK tidak pernah membuat folder log, agar log tidak diam-diam tertulis di disk lokal ketika penyimpanan terpisah belum dipasang. `tapak jangkar mulai` mencatat awal log di registri (entri `anchor_log`) dan menulis penanda media (lihat di bawah). Sejak itu semua proses yang menulis registri ini, yaitu CLI, `tapak web`, dan kontainer `app`, harus memakai `TAPAK_ANCHOR_LOG` yang sama; proses tanpa log menolak pelacakan dan penerbitan. Antarmuka web tidak memiliki halaman pengaturan: jalankan `tapak --log-jangkar /mnt/jangkar/tapak.log web` atau atur variabelnya sebelum server dijalankan. Halaman Registri menampilkan keadaan log, dan hasil Lacak memuat satu baris tentangnya. Di Docker, pasang penyimpanan itu ke kontainer `app` dan tulis variabelnya di bagian `environment` (belum diuji).

**Penanda media.** Bila penyimpanan terpisah belum dipasang, titik kaitnya hanya folder kosong di disk lokal. Karena itu `tapak jangkar mulai` menulis penanda `.tapak-jangkar-media` di samping log (id-nya tercatat di baris awal log), dan setiap pemeriksaan menolak log tanpa penanda itu. `mulai --ulang` dan `rotasi` hanya membuat log di folder yang sudah bertanda; untuk media baru, atau log dari sebelum ada penanda, tambahkan `--tandai-media`. Perintah itu juga mencetak catatan bila folder log bukan titik kait. Pindahkan penanda bersama log.

**Yang terlihat.** Hasil pelacakan, keluaran CLI, dan berita acara memuat satu baris, misalnya "Log jangkar: cocok dengan registri sampai entri #8; entri baru #8 dicatat di log". `tapak jangkar status` juga menyebut ukuran log dan apakah log dapat ditulis; log yang tidak dapat ditulis menolak pelacakan dan penerbitan, jadi status keluar dengan kode 1. `tapak verify` dan `tapak-verify-registry --log-jangkar` mencocokkan log tanpa mengubah apa pun dan tanpa izin tulis. Jangkar berita acara (`tapak verify --jangkar`) tetap berguna sebagai cadangan manual, misalnya untuk dicatat di luar sistem bersama berkas perkara.

**Ukuran dan rotasi.** Log di atas 256 MiB (sekitar 700.000 baris) tidak dibaca lagi, dan semua pelacakan dan penerbitan ditolak; mulai 192 MiB setiap pemeriksaan memperingatkannya. Sebelum itu, misalnya setahun sekali, teruskan log ke segmen baru:

```bash
tapak jangkar rotasi /mnt/jangkar/tapak-2026.log --alasan "rotasi tahunan"
export TAPAK_ANCHOR_LOG=/mnt/jangkar/tapak-2026.log            # di semua proses: CLI, tapak web, kontainer app
tapak verify --segmen-lama /mnt/jangkar/tapak.log               # rantai segmen tetap dapat diperiksa
```

Rotasi hanya berjalan bila log lama cocok dengan registri. Segmen baru dimulai dengan baris yang mengikat log lama (id, panjang, SHA-256, ujung registri yang dijangkarkannya, pengakuan yang berlaku) dan baris yang menjangkarkan ujung itu lagi; registri mencatatnya (entri `rotate`). Simpan segmen lama (boleh dijadikan hanya-baca); proses yang masih memakainya ditolak dengan pesan yang menunjuk ke segmen baru. Rotasi juga cara pindah lokasi tanpa awal ulang, dan masih dapat membaca log sampai 512 MiB. Jangan menunggu sampai batas: `mulai --ulang` menulis satu baris per entri registri, jadi pada registri sebesar itu log barunya langsung melewati batas. Batasnya tidak dinaikkan karena pemeriksaan pertama setiap proses tetap membaca seluruh segmen.

**Kecepatan.** Dalam satu proses, pemeriksaan berikutnya hanya mengurai dan memverifikasi baris baru dan tidak menghitung ulang hash entri registri yang tidak berubah; hasil lama hanya dipakai bila byte log yang sudah diperiksa masih sama (SHA-256). Pada log 100.000 baris (35 MiB) satu penulisan turun dari sekitar 26 menjadi sekitar 1,5 detik di `tapak web` (mesin bersama yang sibuk, `scripts/bench_jangkar.py`). Perintah CLI tetap memeriksa penuh sekali, sekitar 26 detik pada ukuran itu.

**Bila proses mati.** Baris ditulis setelah entri tersimpan. Bila proses mati di antaranya, log tertinggal satu entri, dan penulisan berikutnya melengkapinya otomatis. Log yang tidak dapat ditulis (misalnya penyimpanan hanya-baca) ditolak sebelum entri baru dicatat. Pelacakan yang barisnya tetap gagal ditulis setelah entrinya tersimpan dibatalkan sebelum bukti dibaca, dan nomornya tetap terpakai. Baris yang terpotong karena mati listrik diabaikan dengan peringatan. `tapak jangkar mulai` yang terputus diselesaikan dengan menjalankan perintah yang sama lagi.

**Bila pelacakan ditolak.** Pesannya menyebut entri yang hilang, diganti, atau diubah. Jalankan `tapak verify` untuk rinciannya, lalu:

1. **Log hilang atau tidak terbaca.** Pasang kembali penyimpanannya atau perbaiki izinnya. Jangan menghapus atau mengganti log. Bila log memang hilang, periksa dulu registri dengan jangkar dari berita acara (`tapak verify --jangkar`) atau akar Merkle, lalu mulai log baru secara sadar: `tapak jangkar mulai --ulang --alasan "media jangkar rusak, diperiksa Kasi Ops"`. Awal yang baru tercatat di registri (`restart`) dan alasannya di baris pertama log baru. Log lama yang dipasang kembali sesudahnya ditolak karena sudah diganti, dan setiap hasil pelacakan dan `tapak verify` sesudahnya menyebut awal ulang ini. Bila pesan menyebut log sudah diganti log lain padahal tidak ada yang sengaja memulai ulang, jangan pindah ke log baru itu: periksa registri dengan log lama.
2. **Entri hilang atau diganti.** Kembalikan registri dari cadangan yang masih memuat entri itu; pemeriksaan berikutnya lulus sendiri. Bila entri itu memang tidak dapat dikembalikan, jalankan `tapak jangkar akui --alasan "..."` untuk melihat entri yang akan dilepas, lalu ulangi dengan `--ya`. Pengakuan tercatat di registri (`ack`) dan di log, dan setiap hasil pelacakan sesudahnya menyebutnya. Nomor dan jatah eps pelacakan yang hilang dapat terpakai lagi, jadi batas tuduhan salah gabungan dokumen itu tidak lagi terjamin.
3. **Entri diubah, rantai rusak, atau baris log dipalsukan.** Pengakuan tidak dapat melepasnya. Kembalikan registri atau log dari cadangan dan periksa siapa yang mengubahnya.

Alasan disimpan sebagai teks di log jangkar dan sebagai hash di registri; jangan menulis isi dokumen atau nama penerima di dalamnya. Belum ada perintah untuk berhenti memakai log jangkar pada registri yang sudah memakainya; untuk pindah lokasi, pakai `tapak jangkar rotasi`.

## Kanal pilihan kata (opsional)

Kanal ini hanya untuk dokumen induk PDF dan hanya aktif bila penerbit memberikan `--leksikal` (atau memindai titiknya di halaman Terbitkan, lihat [antarmuka web](#antarmuka-web)). Tanpa itu, penerbitan sama persis dengan sebelumnya.

1. **Pindai.** `tapak leksikal scan dok.pdf -o leksikal.json` mencari titik dengan tabel leksikon draf (`tapak/assets/leksikon/naskah_dinas_v1.json`; `--tingkat AB` ikut memakai kata isi tingkat B). Keluarannya menyebut jumlah titik dan bit, penolakan per kategori, dan perkiraan apakah dokumen cukup panjang untuk satu pembocor.
2. **Tinjau.** `tapak leksikal show leksikal.json` menampilkan setiap titik dengan seluruh kalimatnya (lintas baris), frasa dalam kurung siku, semua bentuknya, dan catatan aturannya (`--status menunggu` hanya menampilkan yang belum diputuskan). Titik bertanda "konteks berulang" memiliki frasa dan konteks yang sama di bagian lain dokumen; tolak titik itu bila bocoran dapat menukar urutan kalimat. Putuskan dengan salah satu cara berikut:
   * satu per satu: `tapak leksikal review leksikal.json --interaktif` (s = setujui, t = tolak, l = lewati, q = selesai);
   * per titik: `--titik l0,l3 --setujui`, `--titik l5 --tolak`, atau `--tunda` untuk mengembalikan ke status menunggu;
   * per aturan: `--aturan dan --tolak`. Persetujuan sekaligus per aturan atau `--semua` memerlukan `--ya`, setelah setiap titiknya dibaca.
3. **Terbitkan.** `tapak issue dok.pdf penerima.csv --leksikal leksikal.json` (boleh bersama `--semantic`). Penerbitan ditolak bila masih ada titik menunggu, bila titik atau bentuknya disunting di luar TAPAK, bila tabel leksikon berubah sejak pemindaian, atau bila pita bias 0,3 sampai 0,7 tidak cukup untuk semua bit (tolak sebagian titik atau pakai c lebih besar). Keluarannya menyebut jumlah bit tahan ketik ulang (pilihan kata dan semantik) dan jumlah kata isi. "Cukup untuk satu pembocor" baru muncul pada 64 bit atau lebih; di bawahnya keluaran menyebut kekurangan bit dan perkiraan kata isi tambahan.
4. **Simpan.** `leksikal.json` memuat teks dokumen. TAPAK menyimpannya di folder dokumen, di samping `induk.pdf` dan `varian.json`; registri hanya menyimpan digest-nya. Keputusan setuju atau tolak di berkas ini tidak diautentikasi, jadi simpan berkas itu di tempat yang hanya dapat ditulis penerbit, sebelum dan sesudah penerbitan. Saat pelacakan, berkas ini dicocokkan dengan digest di catatan penerbitan. Bila hilang atau tidak cocok, kanal pilihan kata dilewati dengan peringatan, dan kanal lain tetap dibaca.
5. **Baca hasilnya dengan hati-hati.** Nama yang hanya didukung pilihan kata dan varian kalimat diberi peringatan di bawah putusan: siapa pun yang pernah membaca salinan itu dapat meniru pilihan katanya. Nama seperti itu memerlukan bukti pendukung.

## Dokumen induk hasil pindai

PDF hasil pindai diterbitkan dengan perintah yang sama, tanpa opsi tambahan:

```bash
tapak issue nota_pindaian.pdf penerima.csv
make samples-pindaian        # contoh fiktif 300 dpi di samples/generated/ (tidak di-commit)
```

* **Resolusi.** Setiap halaman pindaian minimal 200 dpi; 300 dpi disarankan. Di bawah itu penerbitan ditolak dengan pesan yang menyebut halaman dan resolusinya. Geser 0,05 mm tinggal 0,4 piksel pada 200 dpi dan 0,3 piksel pada 150 dpi, galat bit geser pada foto naik saat resolusi turun, dan Tesseract dibuat untuk sekitar 300 dpi ([batasan 8](keamanan.md#batasan)).
* **Yang ditolak.** Halaman pindaian yang diputar (`/Rotate`), gambar dengan masker (transparansi atau warna) atau konten opsional, dan satu gambar yang dipakai di beberapa halaman belum didukung. Halaman yang memuat teks terlihat di atas gambar diperlakukan sebagai halaman teks: hanya teks itu yang ditandai. Bila halaman itu juga berlapis OCR tak terlihat, kata OCR ikut tergambar ulang dan gerbang visual menolak penerbitan. Halaman yang tersusun dari beberapa gambar (misalnya kompresi MRC: latar dan masker teks terpisah) tidak dikenali sebagai halaman pindaian: tanpa lapisan teks halaman itu tidak membawa tanda, dan dengan lapisan OCR penerbitan ditolak.
* **Tesseract.** `tesseract-ocr` dan `tesseract-ocr-ind` diperlukan saat menerbitkan dan saat melacak, dengan versi yang sama. Pelacakan membaca ulang kotak kata (beberapa detik per halaman). Bila hasilnya berbeda dari saat penerbitan, kanal geser halaman pindaian dilewati dengan catatan, dan pola latar tetap dibaca. Simpan versi Tesseract bersama instalasi TAPAK.
* **Keluaran.** Rencana penandaan menyebut mode setiap halaman (teks atau pindaian), kanal yang berlaku, dan lapisan OCR yang dibuang. Gerbang menyatakan bahwa salinan tanpa tanda identik piksel demi piksel dengan induk. Gambar halaman salinan disimpan tanpa kompresi lossy, jadi salinan jauh lebih besar dari induk JPEG-nya (contoh 300 dpi: sekitar 2,9 MB per halaman, induk 0,7 MB per halaman). Ukuran rata-rata dan terbesar dicetak setelah penerbitan.
* **Antarmuka web.** Halaman Terbitkan menerima induk hasil pindai dan dokumen campuran. Kotak kata dibaca dengan Tesseract saat analisis, beberapa detik per halaman. Rencananya menyebut mode setiap halaman, jumlah kotak kata (tanpa katanya), hash daftar kotak, lapisan OCR yang dibuang, gerbang identik piksel, syarat Tesseract yang sama saat pelacakan, serta contoh ukuran dan waktu terukur (bukan perkiraan untuk dokumen itu). Bila semua halaman hasil pindai, langkah Tinjau teks (kalimat aman dan pilihan kata) ditandai tidak berlaku. Setelah terbit, halaman hasil menyebut ukuran salinan yang diukur pada berkasnya. Pelacakan dokumen hasil pindai lebih lama, karena kotak kata dibaca ulang dan halaman pindaian pada bukti dibaca sebagai gambar (contoh: satu PDF salinan 2 halaman sekitar 40 detik). Halaman Lacak menyebut di bawah tabel kanal apakah kanal geser mencakup halaman pindaian, dan menampilkan catatan kanal geser halaman pindaian yang dilewati di samping putusan.

## Antarmuka web

Antarmuka web punya dua halaman utama:

* **Terbitkan**: unggah PDF (berlapis teks atau hasil pindai) dan CSV penerima, pilih profil pola latar (layar atau cetak), lihat rencana penandaan dan gerbang visual, pilih kalimat aman, lalu tinjau setiap varian LLM. Kanal pilihan kata bersifat opsional: penerbit memindai titiknya, membaca setiap kalimat, lalu menyetujui atau menolak per titik (untuk aturan dengan beberapa titik, persetujuan sekaligus meminta konfirmasi; menolak sekaligus tidak). Halaman itu menampilkan jumlah bit tahan ketik ulang dengan perkiraan apakah cukup untuk satu pembocor, penolakan otomatis per kategori (tanpa kata dokumen), dan contoh baris dua salinan yang berbeda kata. Tombol terbit terkunci sampai semua varian dan titik disetujui atau ditolak, dan selama salinan diterbitkan keputusan tidak dapat diubah. Bila tidak ada titik yang disetujui, salinan diterbitkan tanpa kanal ini. Setelah terbit, unduh ZIP.
* **Lacak**: pilih dokumen, lalu unggah foto, tangkapan layar, PDF, atau DOCX, atau tempel teks. Beberapa berkas dari kebocoran yang sama (misalnya foto tiap halaman) boleh dipilih sekaligus dan digabung dalam satu pelacakan. Hasilnya menampilkan putusan, skor, ambang, peluang tuduhan salah, kanal yang sepakat, nama yang ditemukan tahap lanjutan [pelacakan bertahap](cara-kerja.md#pelacakan-bertahap) (di bawah nama tahap 1, bersama salinan dasarnya), status registri, peringatan kanari, dan tombol unduh berita acara.

Halaman PDF tanpa lapisan teks yang cocok (hasil pindai) atau dengan lapisan teks OCR tak terlihat dibaca sebagai gambar. Halaman yang diperkecil, digeser, atau dicetak ke ukuran kertas lain lebih dulu dinormalkan ke bingkai dokumen induk (skala dan pergeseran per halaman). Setelah itu, kanal geser dibaca dari teksnya dan pola latar dari gambarnya.

Halaman **Registri** menampilkan status rantai, [log jangkar](#log-jangkar-eksternal-opsional), kunci publik, akar Merkle, dan peringatan kanari.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="img/ui-terbitkan-dark.png">
  <img alt="Langkah rencana penandaan di halaman Terbitkan: jumlah halaman, panjang kode, ambang, dan kapasitas setiap kanal" src="img/ui-terbitkan-light.png" width="100%">
</picture>

## LLM lokal untuk kanal semantik

Tanpa konfigurasi, varian semantik berasal dari tabel frasa tiruan (`TAPAK_LLM=mock`). Untuk memakai model sungguhan, jalankan `llama-server` dari llama.cpp di komputer yang sama. Langkah berikut sudah diuji dengan llama.cpp b11669 (v0.7.0) di Linux x64 tanpa GPU dan tanpa sudo.

1. Unduh build CPU resmi dari halaman rilis `ggml-org/llama.cpp` (berkas `llama-<tag>-bin-ubuntu-x64.tar.gz`), cocokkan SHA-256-nya dengan digest di halaman rilis, lalu ekstrak:

   ```bash
   mkdir -p ~/llm/bin ~/llm/models
   curl -LO https://github.com/ggml-org/llama.cpp/releases/download/b11669/llama-b11669-bin-ubuntu-x64.tar.gz
   sha256sum llama-b11669-bin-ubuntu-x64.tar.gz   # cf07c1c1...07f65ac
   tar -xzf llama-b11669-bin-ubuntu-x64.tar.gz -C ~/llm/bin
   ```

2. Unduh model instruct GGUF yang mampu berbahasa Indonesia, lalu cocokkan SHA-256-nya dengan yang tercantum di Hugging Face:

   ```bash
   curl -L -o ~/llm/models/MODEL.gguf https://huggingface.co/<repo>/resolve/main/<berkas>.gguf
   sha256sum ~/llm/models/MODEL.gguf
   ```

3. Jalankan server hanya di loopback, dengan port yang ditulis jelas. Port bawaan llama-server berubah dari 8080 menjadi 9931 pada v0.7.0, dan port 8080 sering dipakai layanan lain.

   ```bash
   ~/llm/bin/llama-b11669/llama-server -m ~/llm/models/MODEL.gguf \
     --host 127.0.0.1 --port 8799 -t 4 -c 4096 -np 1 --no-webui
   ```

4. Arahkan TAPAK ke server itu, lalu jalankan alur biasa:

   ```bash
   export TAPAK_LLM=llamacpp TAPAK_LLM_URL=http://127.0.0.1:8799
   tapak semantic suggest dok.pdf -o varian.json   # perlu beberapa menit di CPU
   tapak semantic approve varian.json --unit u0 --variant 1   # setelah dibaca manusia
   tapak issue dok.pdf penerima.csv --semantic varian.json
   ```

   Varian dari model disetujui satu per satu: `approve --all` dan tombol "Setujui semua" di web hanya tersedia untuk tabel frasa tiruan. `--all --reject` tetap boleh.

Sebelum mengirim kalimat dokumen, TAPAK memeriksa bahwa alamat itu menjawab `GET /v1/models` dengan daftar model. Bila tidak, misalnya karena port itu milik layanan lain atau kontainer, TAPAK berhenti tanpa mengirim teks. Permintaan dikirim ke `/v1/chat/completions`, sehingga templat obrolan model dipakai. Alamat lama yang berakhiran `/completion` tetap diterima. Jangan isi `TAPAK_LLM_MODEL` kecuali llama-cpp-python terpasang, karena variabel itu memilih jalur di dalam proses. Batas waktu per permintaan 120 detik dan dapat diubah dengan `TAPAK_LLM_TIMEOUT`.

`tapak semantic suggest` mencetak varian yang lolos dan jumlah kandidat yang dibuang beserta alasannya. Tiap kalimat memerlukan satu panggilan parafrase dan satu panggilan pemeriksa untuk setiap kandidat yang lolos pemeriksaan otomatis. Baca setiap varian sebelum menyetujuinya. Pemeriksa model meloloskan banyak kalimat yang menambah keterangan atau menghapus "Demikian" dan "Dengan hormat" (lihat [batasan](keamanan.md#batasan)).

Model yang sudah diuji (CPU 4 utas di mesin yang dipakai bersama, 2 dokumen contoh):

| Model (GGUF Q4_K_M) | Berkas, RAM | Median per panggilan (parafrase, pemeriksa) | Varian disetujui manusia |
|---|---|---|---|
| Qwen2.5-3B-Instruct (`Qwen/Qwen2.5-3B-Instruct-GGUF`, lisensi Qwen Research) | 2,1 GB, 1,9 GB | 24 s, 9 s | 3 dari 12 varian yang lolos pemeriksa |
| Gemma 3 4B it (`bartowski/google_gemma-3-4b-it-GGUF`, lisensi Gemma) | 2,5 GB, 2,7 GB | 30 s, 14 s | 2 dari 7 varian yang lolos pemeriksa |

Kedua model belum cukup baik untuk kanal ini. Qwen2.5-3B sering hanya mengulang kalimat asli, sedangkan Gemma 3 4B menulis bahasa Indonesia yang lancar tetapi menulis ulang terlalu bebas. Periksa lisensi model sebelum dipakai di luar penelitian.

Di Docker, loopback kontainer `app` adalah kontainer itu sendiri, jadi server di loopback host tidak terjangkau. Jalur ini belum diuji di Docker.

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
| `TAPAK_LLM_MODEL` | berkas GGUF untuk llama-cpp-python di dalam proses (opsional; kosongkan untuk memakai `llama-server`) |
| `TAPAK_LLM_URL` | alamat `llama-server` lokal, misalnya `http://127.0.0.1:8799`; bawaan `http://127.0.0.1:8080`; alamat selain loopback ditolak |
| `TAPAK_LLM_TIMEOUT` | batas waktu per permintaan ke LLM dalam detik; bawaan 120 |
| `TAPAK_ALLOWED_HOSTS` | nama host yang dilayani aplikasi web; bawaan `127.0.0.1,localhost` |
| `TAPAK_SIGNING_KEY`, `TAPAK_PUBLIC_KEY` | lokasi kunci tanda tangan dan kunci publik registri; bawaan di `TAPAK_KEY_DIR` |
| `TAPAK_ANCHOR_LOG` | berkas [log jangkar](#log-jangkar-eksternal-opsional) di penyimpanan terpisah (sama dengan `tapak --log-jangkar`); kosong = tidak dipakai |
| `TAPAK_CANARY_NS_IP` | alamat IPv4 publik pendengar kanari untuk `ns1.<domain>`, sama dengan glue di registrar |
| `TAPAK_CANARY_ANSWER_IP` | (docker-compose) alamat IPv4 jawaban untuk nama kanari; bawaan `127.0.0.1` |

## Pengujian

`make test` menjalankan seluruh suite pytest:
- kode Tardos dan dekoder, dengan uji untuk setiap fungsi publik;
- penanda, kanal 3 lewat MuPDF dan poppler, ketidakterlihatan pada 600 dpi;
- foto dan tangkapan layar, kolusi, jalur "tidak cukup bukti";
- simulator printer, profil latar cetak, dan templat induk tepat;
- registri dan perusakannya, kanari DNS di bawah 5 detik, kanal semantik dengan salah ketik;
- log jangkar: entri yang dihapus dari ujung, diganti, atau diubah, log yang hilang, jendela mati listrik, tanda tangan baris, pengakuan dan awal ulang, batas ukuran dan rotasi (rantai segmen), pemeriksaan bertahap yang sama dengan pemeriksaan penuh, log yang tidak dapat ditulis, penanda media, kode keluar 3 `tapak verify` tanpa log, isi log tanpa data dokumen, CLI, berita acara, dan web;
- kanal pilihan kata: tabel leksikon, token terlindungi pada setiap kombinasi bentuk, tata letak, berkas yang disunting, teks ketikan ulang dan potongan, dokumen lama yang tidak berubah;
- dokumen induk hasil pindai: deteksi per halaman, gerbang identik piksel, salinan tanpa lapisan OCR, pelacakan PDF dan foto, penolakan saat kotak kata berubah;
- DOCX, berita acara, antarmuka web end-to-end;
- penerbitan biasa yang tetap mengundi rahasia kode dan id salinan, dan penerbitan riset dengan benih tetap;
- aturan kebersihan repositori (sumber Python hanya ASCII, tanpa tanda pisah panjang).

Suite ini tidak memerlukan GPU, model LLM, atau jaringan. Uji foto ditandai `slow`, dan `make test-fast` melewatinya.

## Benchmark foto

`make photos`, `make photos-cetak`, lalu `make bench` membuat ulang `docs/results/bench_photos.json`, sumber angka benchmark di README. Penerbitan di belakang kedua set foto (20 salinan tanpa registri di `out/photos`) memakai `tapak issue --benih-riset 2026`: rahasia kode dan id salinan diturunkan dari benih itu, bukan diundi, dan foto memakai benih 2026 sendiri. Karena benihnya publik, siapa pun dapat membuat ulang kode setiap salinan, jadi opsi ini hanya untuk riset. TAPAK menolaknya tanpa `--no-registry`, tidak pernah menimpa rahasia kode yang sudah ada, dan menolak penerbitan biasa di folder kunci yang rahasianya berasal dari benih riset (penanda `code_secret.riset`). Penerbitan biasa tetap mengundi rahasia kode dan id salinan. Folder `out/photos` dari penerbitan lama dengan id acak ditolak; hapus dulu.

`make bench-check` menjalankan ketiga langkah dari awal di `out/bench-check` lalu membandingkan hasilnya dengan `docs/results/bench_photos.json` byte demi byte (sekitar 9 menit di mesin uji yang dipakai bersama). Perhitungan dan OCR berjalan satu utas, jadi hasilnya tidak bergantung pada jumlah utas. Kesamaan byte demi byte berlaku untuk versi pustaka yang sama; dengan numpy, OpenCV, MuPDF, atau Tesseract versi lain, angkanya dapat sedikit berbeda.

## Mengukur salinan yang dicetak

Angka salinan cetak di [cara kerja](cara-kerja.md#salinan-yang-dicetak) dan [batasan 3](keamanan.md#batasan) dapat dibuat ulang dengan `scripts/cetak/` (hasil di `out/cetak`, atau `CETAK_OUT`):

```bash
export PYTHONPATH=.
M=".venv/bin/python -m scripts.cetak.measure"
$M trials --profile layar --long 1600,4000                         # 20 salinan, 2 halaman
$M trials --profile layar --long 1600,4000 --template supersampled # templat lama, foto yang sama
$M trials --profile cetak --long 1600,4000
$M composites --profile cetak --coalitions 16 --long 1600
$M trials --profile cetak --printer inkjet --seqs 1-10 --pages 0 --long 1600
$M report --json docs/results/cetak_summary.json                   # tabel per profil, printer, resolusi
# profil cetak pada cetakan, foto, dan koalisi baru (tidak ikut memilih profil)
export CETAK_OUT=out/cetak-r1 CETAK_ISSUED_CETAK=out/cetak/issued-cetak
$M trials --profile cetak --long 1600,4000 --reps 1
$M composites --profile cetak --coalitions 16 --long 1600 --reps 1
$M trials --profile cetak --printer inkjet --seqs 1-10 --pages 0 --long 1600 --reps 1
$M report --json docs/results/cetak_summary_r1.json
unset CETAK_OUT CETAK_ISSUED_CETAK
.venv/bin/python -m scripts.cetak.visibility        # rona abu-abu dan tekstur (S-CIELAB)
.venv/bin/python -m scripts.cetak.calibrate         # kalibrasi model printer
.venv/bin/python -m scripts.cetak.needbits          # posisi terbaca yang diperlukan per jejak
```

Setiap profil diterbitkan sekali untuk 100 penerima fiktif. Id salinan diundi saat penerbitan, jadi penerbitan baru memberi kode lain dan angka yang sedikit berbeda; `CETAK_ISSUED_LAYAR` atau `CETAK_ISSUED_CETAK` memakai ulang folder penerbitan yang ada. Tabel profil bawaan memakai penerbitan dari riset sebelumnya, yang id salinannya tidak ada di repositori. Hasil di `docs/results/cetak_*` diukur sebelum kanal latar memakai strata kejenuhan dan uji pilot; perintah di atas kini memakai dekoder sekarang, jadi angka profil cetak dapat berbeda. Satu foto cetak memerlukan sekitar 20 sampai 60 detik (1600 px) atau 1 sampai 2 menit (4000 px) per proses di mesin uji yang dipakai bersama; `--workers` mengatur jumlah proses (bawaan 3).
