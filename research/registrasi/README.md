# Registrasi bukti potongan dan beresolusi rendah

Studi tangkapan layar ([`research/layar`](../layar/README.md)) menemukan bahwa registrasi, bukan dekoder, yang menentukan batas bawah: setiap halaman utuh yang gagal adalah halaman yang tidak ditemukan (28 sampai 32 dpi; Splash tanpa anti-aliasing sampai 48 dpi), jendela penampil yang hanya memperlihatkan bagian tengah halaman tidak ditemukan pada 60 dari 120 tangkapan, dan setiap halaman yang ditemukan disebut. Pembocor juga sering mengirim potongan satu paragraf atau foto ponsel sebagian halaman. Studi ini mengukur bukti mana yang gagal diregistrasi dan tahap mana yang menyerah, lalu mengukur tahap penyelamat yang dipilih pada set pengembangan (`tapak/decoder/rectify.py`, `rescue_register`) pada set uji yang ditahan, sebelum dan sesudah.

## Protokol

Protokol, benih, dan aturan pemilihan ditetapkan di `ukur.py` (`PROTOCOL`) dan `pilih.py` (`ATURAN`) dan masuk riwayat repositori sebelum set uji dibuat.

* **Penerbitan.** Nota dinas dan surat telegram contoh (fiktif) lewat `tapak issue --benih-riset BENIH --no-registry` untuk N = 20 penerima (c = 3, eps = 10^-6, skema geser v2, profil latar bawaan). Benih baru yang belum dipakai studi lain: set `dev` 9601 dan 9602 (benih bukti 9611, induk tanpa tanda 9699), set `uji` 9701 dan 9702 (9711, 9799). Bukti diambil dari halaman 1 dan halaman 2.
* **Jenis bukti** (`PROTOCOL["grids"]`):
  * `potong`: tangkapan layar yang digambar penggambar sungguhan dari `research/layar` (MuPDF, Poppler Splash, Poppler Cairo), bagian atas, tengah, atau bawah halaman setinggi 25, 40, 55, 70, 85, atau 100 % (100 % hanya dari atas), selebar halaman, dengan dan tanpa jendela penampil (bergantian), pada 48, 64, 84, 120, dan 150 dpi, disimpan sebagai PNG atau dikirim lewat aplikasi pesan (`pesan`: sisi panjang paling besar 1600 px, JPEG mutu 68 sampai 72 lalu 58 sampai 62);
  * `paragraf`: potongan satu paragraf (barisnya ditambah tepi 3 sampai 12 pt, tanpa jendela), resolusi dan format seperti `potong`;
  * `rendah`: halaman utuh pada 24, 28, 32, 40, dan 48 dpi, keempat penggambar (termasuk Splash tanpa anti-aliasing), PNG, `pesan`, dan `kecil` (digambar 1,5 kali lebih rapat lalu diperkecil aplikasi pesan), halaman saja atau di jendela penampil;
  * `foto`: foto ponsel halaman utuh dari `tapak.photos.photo_jpeg` (0 sampai 30 derajat, sensor 4000 px, JPEG kamera mutu 90 sampai 95, separuhnya lewat ISP ponsel), dipotong pengguna menjadi bagian atas, tengah, atau bawah setinggi 25 sampai 70 % atau satu paragraf, lalu dikirim lewat aplikasi pesan;
  * `induk`: dokumen induk tanpa tanda lewat keempat jenis di atas, dilacak terhadap penerbitan dokumennya: tidak boleh ada yang dituduh;
  * `silang`: satu dari setiap delapan bukti salinan bertanda, dilacak terhadap penerbitan dokumen yang lain. Setiap registrasi di sini salah dokumen dan setiap tuduhan salah. Kedua dokumen memakai font, tepi, kop, dan kaki halaman yang sama, jadi ini uji terberat bagi verifikasi pose.
* **Pelacakan** seperti `make bench`: tanpa registri, seluruh eps, satu tahap, lewat jalur produksi (`collect_from_gray`). Bila tahap penyelamat berjalan, gambar yang sama dilacak sekali lagi dengan tahap itu dimatikan (`register(..., rescue=False)`, jalur sebelum studi ini), sehingga sebelum dan sesudah berpasangan.
* **Kebenaran pose.** Setiap gambar membawa homografi sebenarnya dari titik halaman ke piksel gambar. Galat pose diukur di gambar pada titik berjarak 14 pt di bagian halaman yang terlihat, dan pada titik tengah kata induk yang terlihat. Pose **benar** bila persentil ke-95 seluruhnya paling besar 1,5 piksel gambar; **salah** bila halaman atau dokumennya salah, tidak ada kata induk yang terlihat, atau persentil ke-95 pada kata lebih dari 5 piksel; selebihnya **kasar** (teks pas, bagian kosong meleset, misalnya potongan yang hanya memuat kaki halaman).
* **Ukuran per pelacakan.** Ditemukan atau tidak, kelas pose, tahap yang menyerah (`ringkas.py`, `stage`), putusan semua kanal, skor salinan yang bocor dan skor tak bersalah tertinggi sebagai kelipatan ambang, batas peluang tuduhan salah, peringatan pola penghapusan, peringatan bacaan jelas tanpa nama, dan detik per pelacakan.

## Tahap yang menyerah (set dev, jalur sebelum studi ini)

(diisi)

## Tahap penyelamat

Tahap ini hanya berjalan bila tahap sebelumnya tidak menemukan halaman (tidak ada pose awal, atau korelasi ECC di bawah 0,75). Semua yang ditemukannya dipilih pada set dev; dekoder dan registrasi tetap buta kode (hanya bukti, PDF induk, dan ukuran halaman).

(diisi)

## Hasil (set uji)

(diisi)

## Menjalankan

```bash
export TAPAK_REGISTRASI_KERJA=/jalur/kerja    # bawaan: out/riset_registrasi (besar, tidak di-commit)
python research/registrasi/ukur.py terbit --split dev
python research/registrasi/ukur.py lacak --split dev --berkas dev_sebelum.jsonl   # jalur sebelum studi (tahap penyelamat belum ada)
python research/registrasi/pilih.py kumpul --hanya-gagal dev_sebelum.jsonl       # registrasi saja, set dev
python research/registrasi/pilih.py pilih                                       # aturan: hasil/pilihan.json
python research/registrasi/ukur.py terbit --split uji
python research/registrasi/ukur.py lacak --split uji                            # sekali, di akhir
python research/registrasi/ringkas.py --split uji --json
```
