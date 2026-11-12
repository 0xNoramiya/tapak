# Foto ponsel sungguhan dari halaman contoh yang dicetak

Sampai 12 November 2026 setiap foto dan cetakan uji TAPAK sintetis ([batasan 10](../../docs/keamanan.md#batasan-10)). Hari itu tim mencetak halaman 1 surat telegram contoh dengan printer sungguhan dan memotretnya dengan dua ponsel: 13 berkas foto dari lima keadaan lembar. Satu berkas (blur/175633) ternyata potongan galeri dari foto lain (miring/175559), jadi pengambilan gambarnya 12.

| Keadaan lembar | Foto | Ponsel |
|---|---|---|
| datar, difoto miring | 3 | vivo 1935 (3264 x 1836) |
| datar, foto buram | 2 | vivo 1935 (3264 x 1836 dan 2368 x 1328) |
| sobek menjadi empat, disusun kembali | 3 | iPhone 11 (4032 x 2268) |
| kusut diremas, diratakan kembali | 2 | iPhone 11 |
| basah (bernoda air, bergelombang) | 3 | iPhone 11 |

Foto tidak ada di repositori: selain halaman contoh fiktif, terlihat meja dan ruangan. Yang disimpan hanya angka: `hasil/foto.jsonl` (satu baris per foto), `hasil/geser.json`, dan `hasil/medan.json` (bentuk setiap lembar, lihat di bawah). `ukur.py` mengulang semuanya dari folder foto.

**Yang tidak diketahui.** Penerbitan asal lembar itu tidak ada di mesin uji, jadi salinan mana yang dicetak, dan apakah lembar itu salinan bertanda atau dokumen induk, tidak diketahui. Studi ini karena itu hanya menjawab tiga hal: apakah halaman ditemukan, apakah ada yang tertuduh, dan seberapa teliti posisi kata terukur. **Apakah salinan yang benar disebut dari cetakan sungguhan belum terjawab.**

## Halaman tidak ditemukan

Dengan registrasi sebelum studi ini, 12 dari 13 foto dijawab "halaman dokumen induk tidak ditemukan", juga foto iPhone yang tajam dan hampir tegak lurus dari lembar yang hampir rata. Pose awalnya benar: SIFT dan kontur menemukan halaman 1 pada 130 sampai 270 dpi. Yang gagal adalah ambang korelasi ECC 0,75: korelasi bidang datar hanya 0,42 sampai 0,70 (satu foto 0,80).

Pada foto yang diperiksa blok demi blok (basah/G_3332), setelah homografi terbaik bagian halaman masih meleset 1,2 mm dan lebih, berbeda arah di bagian yang berbeda, sedangkan hampir setiap blok cocok dengan induk (0,8 sampai 0,95) setelah digeser sendiri. Kertas sungguhan tidak datar, dan lensa ponsel membengkokkan garis lurus. Foto simulasi kami datar sempurna (korelasi 0,92 ke atas pada 40 foto set contoh), jadi kegagalan ini tidak pernah muncul.

## Langkah halaman tidak datar

`rectify.estimate_bend` ([cara kerja](../../docs/cara-kerja.md#registrasi-bukti-gambar)) mengukur sisa itu blok demi blok dan membuat dua medan geser dari pengukuran yang sama: medan halus untuk menjawab "apakah ini halaman induk?" dengan ambang 0,75 yang sama, dan medan mulus (rata-rata 15 mm) untuk meluruskan gambar yang dibaca dekoder.

| Foto | Lembar | Ponsel | Korelasi bidang datar | Setelah medan | Ditemukan | dpi efektif | Posisi terbaca | Skor tertinggi / ambang |
|---|---|---|---|---|---|---|---|---|
| basah/G_3332 | basah | iPhone 11 | 0,63 | 0,92 | ya | 246 | 176 | 0,24 |
| basah/G_3337 | basah | iPhone 11 | 0,53 | 0,90 | ya | 262 | 122 | 0,19 |
| basah/G_3338 | basah | iPhone 11 | 0,53 | 0,91 | ya | 255 | 119 | 0,23 |
| blur/175633 | buram | vivo 1935 | 0,70 | 0,84 | ya | 160 | 163 | 0,17 |
| blur/175737 | buram | vivo 1935 | - | - | tidak | - | - | - |
| kusut/G_3339 | kusut | iPhone 11 | 0,54 | 0,82 | ya | 250 | 107 | 0,16 |
| kusut/G_3341 | kusut | iPhone 11 | 0,59 | 0,83 | ya | 212 | 112 | 0,23 |
| miring/175559 | datar, miring | vivo 1935 | 0,69 | 0,83 | ya | 160 | 160 | 0,11 |
| miring/180037 | datar, miring | vivo 1935 | 0,46 | 0,55 | tidak | - | - | - |
| miring/180124 | datar, miring | vivo 1935 | 0,80 | 0,86 | ya | 134 | 147 | 0,12 |
| sobek/G_3334 | sobek | iPhone 11 | 0,42 | 0,84 | ya | 235 | 79 | 0,19 |
| sobek/G_3335 | sobek | iPhone 11 | 0,56 | 0,88 | ya | 216 | 123 | 0,45 |
| sobek/G_3336 | sobek | iPhone 11 | 0,55 | 0,88 | ya | 238 | 124 | 0,44 |

* **Seberapa tidak datar.** Medan halus yang terukur paling jauh 1,9 sampai 4,6 mm dari bidang datar (lembar kusut paling sedikit: lipatannya kecil-kecil, bukan lengkung besar).
* **Ditemukan: 1 menjadi 11 dari 13.** Dua sisanya foto yang sangat buram: satu kabur gerak (korelasi 0,55 setelah medan), satu difoto dari jauh sehingga teksnya tidak terbaca (ECC tidak konvergen). Jawaban "tidak ditemukan" di sana benar.
* **Dokumen lain tidak ikut lolos.** Foto yang sama terhadap nota dinas contoh (font, tepi, dan kepala halaman yang sama): korelasi setelah medan paling tinggi 0,40. Tiga foto simulasi nota dinas dari set contoh terhadap surat telegram (pemeriksaan sekali jalan, tidak di `hasil/`): 0,54 sampai 0,58, tanpa kenaikan dari medan.
* **Tidak ada yang tertuduh.** Setiap foto dilacak terhadap penerbitan surat telegram lain (20 salinan, skema v2, dibuat untuk studi ini): 13 dari 13 "tidak cukup bukti", skor tertinggi paling besar 0,45 kali ambang.
* **Foto simulasi tidak berubah.** Langkah ini hanya berjalan bila korelasi bidang datar di bawah 0,90; benchmark README terulang byte demi byte (`make bench-check`).

## Seberapa teliti posisi kata terukur

`ukur.py geser` membaca geseran setiap kelompok kata (pengukuran dekoder geser sendiri) dan membandingkannya antarfoto.

* **Kamera cukup teliti.** Tiga pasang foto iPhone memotret lembar yang sama dalam keadaan yang sama (basah, kusut, sobek). Setelah bentuk kertas dibuang (butir ketiga), geseran kelompok kata pada kedua foto hampir sama: korelasi 0,92 sampai 1,00 pada dx dan 0,75 sampai 0,94 pada dy. Bagian yang berbeda antara dua foto, yaitu derau kamera, hanya 0,01 sampai 0,03 pt (3 sampai 10 um) pada lembar basah dan sobek dan 0,05 sampai 0,06 pt pada lembar kusut, di bawah geser skema v2 (0,071 pt, 25 um).
* **Kertasnya yang bergerak.** Setelah medan mulus registrasi dan gangguan baris (geser dan kemiringan per baris) dibuang, kelompok kata masih meleset 0,13 sampai 0,30 pt pada lembar datar, basah, dan sobek, dan 0,32 sampai 0,36 pt pada lembar kusut: dua sampai lima kali geser v2. Pada dy, yang tidak membawa tanda kata, besarnya sama, jadi itu bentuk kertas, bukan tanda.
* **Baris tetangga meramalkan sebagian besar bentuk itu.** Bila geseran setiap kelompok diramal dari kelompok di baris lain di dekatnya (kernel Gauss, baris sendiri tidak ikut), sisa pada dy turun menjadi 0,05 sampai 0,06 pt pada lembar basah dan sobek (iPhone), 0,07 sampai 0,09 pt pada lembar datar (vivo), dan 0,19 sampai 0,22 pt pada lembar kusut (kernel 8 mm sepanjang baris dan 4 mm antarbaris, yang menyisakan paling sedikit pada dy); pada dx sisanya 0,07 sampai 0,12 pt, dan 0,22 sampai 0,25 pt pada lembar kusut. Sisa itu juga melekat pada lembar, bukan pada foto: bentuk kertas yang lebih halus dari jarak baris, letak glif printer, dan tanda geser bila lembar itu bertanda. Dekoder sekarang memakai satu polinomial derajat 3 per halaman dan melaporkan sigma kata 0,08 sampai 0,12 pt pada foto ini, di atas geser v2.

Kesimpulan sementara: pada lembar sungguhan, tanda geser kata v2 (25 um) berada di bawah gerak kertas pada skala kelompok kata. Apakah tanda itu tetap terbaca dengan model bentuk kertas yang lebih baik, dan bagaimana geser baris dan profil latar cetak bertahan, hanya dapat diukur dengan cetakan dari salinan yang diketahui.

## Yang berikutnya

1. Mencetak dan memotret salinan yang diketahui (nomor salinan dicatat), dari penerbitan skema v2 bawaan dan dari penerbitan profil latar cetak, supaya angka "salinan benar disebut" dapat diukur.
2. Dengan foto itu: model bentuk kertas di dekoder geser (medan dari baris tetangga), dan apakah pola latar profil cetak tercetak pada printer sungguhan.

## Mengulang

```bash
tapak --data DATA --keys KEYS keys init
tapak --data DATA --keys KEYS issue samples/surat_telegram.pdf samples/recipients.csv --canary-domain ""
PYTHONPATH=. python research/fotoasli/ukur.py foto FOLDER_FOTO --induk samples/surat_telegram.pdf \
    --lain samples/nota_dinas.pdf --data DATA --keys KEYS --doc HASH
PYTHONPATH=. python research/fotoasli/ukur.py geser
```

Angka lacak (skor dan ambang) bergantung pada penerbitan yang dibuat untuk studi; registrasi dan geseran tidak.
