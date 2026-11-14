from __future__ import annotations

from typing import NamedTuple

PESI_REPO = "numz/SeedVR2_comfyUI"
PESI_REVISIONE = "09ced71023636e9bc8cdf9cdecfb2625d1e691e8"
PESI_LICENZA = "Apache-2.0"
NITIDO = "seedvr2_ema_7b_sharp_fp16.safetensors"
NITIDO_SHA256 = "20a93e01ff24beaeebc5de4e4e5be924359606c356c9c51509fba245bd2d77dd"
NITIDO_BYTE = 16479334424
VAE = "ema_vae_fp16.safetensors"
VAE_SHA256 = "20678548f420d98d26f11442d3528f8b8c94e57ee046ef93dbb7633da8612ca1"


class Ritratto(NamedTuple):
    titolo: str
    indirizzo: str
    larghezza: int
    altezza: int
    sha256: str
    byte: int
    licenza: str
    autore: str
    volto: tuple[float, float, float, float]


RITRATTI = (
    Ritratto(
        'File:14-02-05-straszburg-RalfR-007.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/7/78/14-02-05-straszbur'
         'g-RalfR-007.jpg'),
        2848, 4288, 'f2c885caa3fd67598dc08f75fe5b58a0e2c87b1440d2a6f301f2ba1ab7f57188',
        9505966, 'CC BY 3.0', 'Ralf Roletschek',
        (0.12771, 0.09829, 0.61933, 0.61543)),
    Ritratto(
        'File:Teotihuacán, México, 2013-10-13, DD 58.JPG',
        ('https://upload.wikimedia.org/wikipedia/commons/f/f1/Teotihuac%C3%A1n%2'
         'C_M%C3%A9xico%2C_2013-10-13%2C_DD_58.JPG'),
        4637, 3198, 'd2e743797ae8fbb24f4297ef9a156fe12c285883e347a285fffd40b1d21c6c26',
        6904647, 'CC BY-SA 3.0', 'Diego Delso',
        (0.40413, 0.20065, 0.19477, 0.3884)),
    Ritratto(
        'File:12-06-28-s06-timo-mohaupt-04.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/6/68/12-06-28-s06-timo-'
         'mohaupt-04.jpg'),
        2848, 4288, '0e8003a8e60989781f1b4f94a38d63a05efa190bfb41e92a43c2445b64458dad',
        5180731, 'CC BY-SA 3.0', 'Ralf Roletschek',
        (0.34272, 0.23705, 0.40036, 0.35966)),
    Ritratto(
        'File:Tribu Laarim, Kimotong, Sudán del Sur, 2024-01-24, DD 110.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/a/a5/Tribu_Laarim%2C_Ki'
         'motong%2C_Sud%C3%A1n_del_Sur%2C_2024-01-24%2C_DD_110.jpg'),
        5112, 7668, '3a49445ccec2e91f19aadfd683535bdf4ffc165506ea4723ba21ee87119e7009',
        8762852, 'CC BY-SA 4.0', 'Diego Delso',
        (0.32523, 0.21848, 0.23777, 0.21455)),
    Ritratto(
        'File:P-petrovnina-gm-2452.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/e/e6/P-petrovnina-gm-2452.jpg',
        3160, 4500, '03c00234babe8c8dac22d241d77c0dd9e7c14da29698783255df280026968710',
        3251098, 'CC BY-SA 3.0', 'PereslavlFoto',
        (0.21934, 0.21299, 0.5127, 0.49774)),
    Ritratto(
        'File:Bernardo Penabade.002 - Burela.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/b/bf/Bernardo_Penabade.'
         '002_-_Burela.jpg'),
        4000, 5889, '95fc63109a8eae64c2915ac20b7c6ae4a0eb128fc3250de9ac476397fd7c0773',
        8214951, 'CC BY-SA 4.0', 'Fernando Losada Rodríguez',
        (0.26318, 0.19639, 0.5074, 0.49898)),
    Ritratto(
        'File:Sabine Dittmar 2012 - RalfR.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/a/ae/Sabine_Dittmar_201'
         '2_-_RalfR.jpg'),
        2848, 4288, '6564cc5dbd178e5fc3705d1ae6d022450fc9b1427a4f0f1b2559d1b13f01cde7',
        3980036, 'CC BY-SA 3.0 de', 'Ralf Roletschek',
        (0.31212, 0.21746, 0.46112, 0.38702)),
    Ritratto(
        'File:Freeride World Tour 2014 Chamonix - Christine Hargin.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/0/09/Freeride_World_Tou'
         'r_2014_Chamonix_-_Christine_Hargin.jpg'),
        4375, 2917, '4a22c1f63b41b36480bc2d1596b9d3f56fa386135cde7c83bd205ff855e20842',
        8012408, 'CC BY-SA 3.0', 'Ludovic Péron',
        (0.45143, 0.22831, 0.28142, 0.54987)),
    Ritratto(
        'File:Anne-Marie-4250.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/5/50/Anne-Marie-4250.jpg',
        3799, 5698, 'b89afed6de4b1b8c318594b38a02da930cdc2e54e450e7a508220bbbcde67cbe',
        4363464, 'CC BY-SA 4.0', 'Harald Krichel',
        (0.29661, 0.19992, 0.38049, 0.34342)),
    Ritratto(
        'File:P-vasilieva-mv-9401.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/5/52/P-vasilieva-mv-9401.jpg',
        4700, 3100, '31debaceac2b7b7a29d7d306c1fd40beba689c0935aa31d07bf334fc7c0e6a1c',
        3493358, 'CC BY-SA 3.0', 'PereslavlFoto',
        (0.35379, 0.3148, 0.24468, 0.44703)),
    Ritratto(
        ('File:2017-05-07 Gründungsversammlung der Freiwilligen Feuerwehr Weißen'
         'burg (75).jpg'),
        ('https://upload.wikimedia.org/wikipedia/commons/2/2d/2017-05-07_Gr%C3%B'
         'Cndungsversammlung_der_Freiwilligen_Feuerwehr_Wei%C3%9Fenburg_%2875%29'
         '.jpg'),
        3680, 5520, 'df87a5b6318115b8c756288b1c94dd4508cc2ef529cf35368717f32411adfcaa',
        10695894, 'CC BY-SA 4.0', 'User:GT1976',
        (0.28348, 0.20556, 0.2889, 0.26457)),
    Ritratto(
        'File:Risto Vilhunen.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/4/48/Risto_Vilhunen.jpg',
        2857, 4000, 'bf2805cf5b25155a2cd636909ebb3b06a8bb3fb93dc57c482d698616322ab5ef',
        6044692, 'CC BY 4.0', 'Antti Yrjönen / Vantaa City Museum',
        (0.21898, 0.11917, 0.55291, 0.58632)),
    Ritratto(
        'File:Luciana Carro - 2012 Sci-Fi Convention Toulouse 259.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/4/4a/Luciana_Carro_-_20'
         '12_Sci-Fi_Convention_Toulouse_259.jpg'),
        2832, 4256, '57ce81023fa1b11488094ed7d1bde17eed74bee651d49e33cb31ee52f398f40f',
        8060763, 'CC BY 3.0', 'Guillaume Paumier',
        (0.40934, 0.15823, 0.40608, 0.38231)),
    Ritratto(
        'File:Sophie Österberg Mars 2013 03.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/9/9d/Sophie_%C3%96sterb'
         'erg_Mars_2013_03.jpg'),
        3267, 4895, 'ae06271fbd09140e5f2f8dd6422d748e5ae771ec28dbf4a4ffe7ce5794a88273',
        4891229, 'CC BY-SA 3.0', 'Arild Vågen',
        (0.22763, 0.23905, 0.43373, 0.40647)),
    Ritratto(
        'File:Zoe Lyons Cigar Wink High Res.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/0/03/Zoe_Lyons_Cigar_Wi'
         'nk_High_Res.jpg'),
        2848, 4288, '48757913cbf067ba7b85bfc05f87e0a55d1a3670566075702ce4e9dde2ef4c97',
        2359717, 'CC BY-SA 3.0', 'Steve Ullathorne',
        (0.34856, 0.24962, 0.32874, 0.32876)),
    Ritratto(
        'File:Colin Cunningham - 2012 Sci-Fi Convention Toulouse 262.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/a/a9/Colin_Cunningham_-'
         '_2012_Sci-Fi_Convention_Toulouse_262.jpg'),
        2832, 4256, '7f28c46acfe021dbd3b968607d2da1d29afba87dedd1cca3a9ccfe7540291a64',
        7932661, 'CC BY 3.0', 'Guillaume Paumier',
        (0.33951, 0.1272, 0.3848, 0.38504)),
    Ritratto(
        'File:Grinning Laotian showing teeth.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/2/26/Grinning_Laotian_s'
         'howing_teeth.jpg'),
        6054, 4036, 'd5e30f9684bc77e6e272f87c1f97671e26371cd89e6e4497c0fab807ca5f36c4',
        2636809, 'CC BY-SA 4.0', 'Basile Morin',
        (0.33426, 0.16926, 0.375, 0.75906)),
    Ritratto(
        'File:HH Polizeihauptmeister MZ.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/c/ce/HH_Polizeihauptmei'
         'ster_MZ.jpg'),
        2912, 4368, '1b88b44cb8a1caf2da4ec55dad2bdc2a27c8a729d27e12c0340393a796af14e0',
        4621985, 'CC BY-SA 2.5', 'Daniel Schwen',
        (0.3291, 0.26165, 0.23311, 0.18508)),
    Ritratto(
        'File:Bernard Ramanantsoa HEC 12 juin 2015.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/2/2b/Bernard_Ramanantso'
         'a_HEC_12_juin_2015.jpg'),
        3056, 4592, '5264cfadb75477c291bf5b5ea980d964bc0d3f7ba8d7acef57a5d35d41148e23',
        8719304, 'CC0', 'Jebulon',
        (0.19589, 0.18744, 0.57835, 0.47076)),
    Ritratto(
        'File:Porsche, GIMS 2018, Le Grand-Saconnex (1X7A0239).jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/5/52/Porsche%2C_GIMS_20'
         '18%2C_Le_Grand-Saconnex_%281X7A0239%29.jpg'),
        3584, 4480, 'ab91e6ffa335832b920169b96bfbb6523177d722a91c39f9dda12109450d38a9',
        5657282, 'CC BY-SA 4.0', 'Matti Blume',
        (0.29078, 0.25251, 0.3382, 0.41143)),
    Ritratto(
        'File:Maddalena Soler Baraban Bardentreffen 2014 So 1042.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/f/f7/Maddalena_Soler_Ba'
         'raban_Bardentreffen_2014_So_1042.jpg'),
        4288, 2848, 'bac79481ef5e46db9418d52805f72fb06c2e358908c9ebe4c51b6cb2d5e35747',
        3136106, 'CC BY-SA 4.0', 'Rs-foto',
        (0.39335, 0.09839, 0.20921, 0.45752)),
    Ritratto(
        'File:13-05-23-schmidl-doris-08.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/7/7a/13-05-23-schmidl-d'
         'oris-08.jpg'),
        2848, 4288, '86b56f99c2e53ab6b6c18deca244125cc7e538a2b52d7d36340047ff4570b0bb',
        3586290, 'CC BY-SA 3.0', 'Ralf Roletschek',
        (0.28784, 0.20748, 0.41116, 0.37871)),
    Ritratto(
        'File:Rose McGowan (12663).jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/1/14/Rose_McGowan_%2812'
         '663%29.jpg'),
        4608, 3456, 'c9ac98025f67f0b3ac1d8bd63159a23a21235c8a2692ea1bba3046e1a8e425c5',
        7844551, 'CC BY-SA 4.0', 'Rhododendrites',
        (0.27836, 0.17511, 0.20469, 0.39697)),
    Ritratto(
        'File:Magdalena Biejat Sejm 2019.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/8/88/Magdalena_Biejat_S'
         'ejm_2019.jpg'),
        4875, 6444, 'a11ac5b64ab008467b6ac0e7132ce41cdb5413ac37b7d3ffde32bf1f33225d52',
        17685369, 'CC BY-SA 3.0 pl', 'Adrian Grycuk',
        (0.31223, 0.20287, 0.40835, 0.41271)),
    Ritratto(
        'File:Imene6.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/4/4d/Imene6.jpg',
        3456, 5184, '1c338666388eaba2b821ff9f1e136179bc1ac50f78e13cd13ace9d78ca563fd9',
        8770825, 'CC BY-SA 4.0', 'Samia Dib Benkaci',
        (0.36888, 0.20521, 0.42942, 0.39395)),
    Ritratto(
        'File:Ana Pascu 2013 Fencing World Championships.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/4/4c/Ana_Pascu_2013_Fen'
         'cing_World_Championships.jpg'),
        3340, 5000, '23de0ca9a3ff4c4f84246603f78f53bb2def7ee5fe5625fc66c4e3bab87b78c4',
        9956540, 'CC BY 3.0', 'Marie-Lan Nguyen',
        (0.23152, 0.16208, 0.51446, 0.43267)),
    Ritratto(
        'File:Eva Nogales in 2023 06.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/a/a7/Eva_Nogales_in_2023_06.jpg',
        5464, 8192, '364ae0c2c3fb2ced33a6415ad5dd2983cea68035d8f179c497fbffb2938f9a47',
        23018693, 'CC BY 4.0', 'Cmichel67',
        (0.47238, 0.16986, 0.24762, 0.23486)),
    Ritratto(
        'File:Festivalgelände Wasteland - Wacken Open Air 2016-AL0320.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/c/cb/Festivalgel%C3%A4n'
         'de_Wasteland_-_Wacken_Open_Air_2016-AL0320.jpg'),
        3840, 5211, '0ee6b3e5e712df22c522c1a0c3816b6c20351b1f750e87ff5a185197c9fc7729',
        7464707, 'CC BY-SA 3.0', 'Andreas Lawen, Fotandi',
        (0.27773, 0.31689, 0.33615, 0.27039)),
    Ritratto(
        'File:Morcheeba - Ottakringer Brauerei Wien 2014 21.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/6/63/Morcheeba_-_Ottakr'
         'inger_Brauerei_Wien_2014_21.jpg'),
        5100, 3400, '6e8f9eb39b1bcbc525185ef2607bb22bc776d7ec52eb0e43c568bb1b7817d867',
        4779860, 'CC BY-SA 3.0', 'Manfred Werner - Tsui',
        (0.37375, 0.2532, 0.18637, 0.39222)),
    Ritratto(
        'File:Professor James Naismith FMedSci FRS.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/4/42/Professor_James_Na'
         'ismith_FMedSci_FRS.jpg'),
        3744, 5616, '92d834def259964c2479b23a97e18f7fa73a7bf030bd0f58d58f0e31611c9e97',
        12494145, 'CC BY-SA 4.0', 'Royal Society uploader',
        (0.40511, 0.11094, 0.21465, 0.20451)),
    Ritratto(
        'File:AGH Berlin 10-2013 img57 Canan Bayram.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/3/31/AGH_Berlin_10-2013'
         '_img57_Canan_Bayram.jpg'),
        3280, 4936, 'd86212b545e91ec52887d79371b3f215895afd667d3e120a7e5f3f745aa1bb0b',
        4974325, 'CC BY-SA 3.0', 'A.Savin',
        (0.29748, 0.21019, 0.4153, 0.38067)),
    Ritratto(
        'File:Wang Chuanfu IAA 2023 1X7A0154.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/3/37/Wang_Chuanfu_IAA_2'
         '023_1X7A0154.jpg'),
        4046, 6064, '3463fce8d22572e7f64a19abe2cd052d55bd784febacd905f4e7aee0e8e99573',
        12881766, 'CC BY-SA 4.0', 'Alexander-93',
        (0.30966, 0.08691, 0.30407, 0.25588)),
    Ritratto(
        'File:Radaja Seto Festival (2016) - 115.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/c/cb/Radaja_Seto_Festiv'
         'al_%282016%29_-_115.jpg'),
        3000, 4512, '42cbaf267b8c331b1fcc2e65868a6703689e391baaecfea0ee0eed11a6a93222',
        8787345, 'CC BY-SA 4.0', 'Ivo Kruusamägi',
        (0.33526, 0.13355, 0.17557, 0.12805)),
    Ritratto(
        'File:Senyszyn, Joanna-2406.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/3/36/Senyszyn%2C_Joanna-2406.jpg',
        2832, 4256, '5d779584eda2af87b35fcc4b3bb43495081d9067cbf786e819f480cbe74da233',
        6932188, 'CC BY-SA 3.0', 'Foto-AG Gymnasium Melle',
        (0.33905, 0.16648, 0.34721, 0.30638)),
    Ritratto(
        'File:Young boy smiling, holding a fighting rooster in Laos.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/7/74/Young_boy_smiling%'
         '2C_holding_a_fighting_rooster_in_Laos.jpg'),
        3816, 5724, '6c4609a9cf8b12f70a757288b227b57034edc8fbe1fdf57bcd5af89f73bd9727',
        8687361, 'CC BY-SA 4.0', 'Basile Morin',
        (0.38521, 0.10973, 0.2238, 0.21411)),
    Ritratto(
        'File:Xavier GUICHARD directeur de la PJ de Paris de 1930 à 1934 (jeune).jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/9/93/Xavier_GUICHARD_di'
         'recteur_de_la_PJ_de_Paris_de_1930_%C3%A0_1934_%28jeune%29.jpg'),
        3640, 5544, '3111739bfa0fa3f27848ca6237369d18fef29f5c9316c8374745b20424750057',
        12672806, 'Public domain', 'AnonymousUnknown author. Jebulon for upload',
        (0.24184, 0.17782, 0.53746, 0.49712)),
    Ritratto(
        'File:Gondar Girl.JPG',
        'https://upload.wikimedia.org/wikipedia/commons/4/45/Gondar_Girl.JPG',
        2848, 4288, '32d875118c6630168341e3bafb89e51a70db35236f8865daa4b1ab950f9b4264',
        6808343, 'CC BY-SA 4.0', 'Natnael Tadele',
        (0.31261, 0.49372, 0.20477, 0.20592)),
    Ritratto(
        'File:OutDoor 2018, Friedrichshafen (1X7A0266).jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/4/4c/OutDoor_2018%2C_Fr'
         'iedrichshafen_%281X7A0266%29.jpg'),
        3230, 4027, '6120bdee66e3fc089a7ca4eff5188eecc0d27e73201fa71bbedf8c8104fcdb0e',
        5956601, 'CC BY-SA 4.0', 'Matti Blume',
        (0.33578, 0.09754, 0.26623, 0.29317)),
    Ritratto(
        'File:Rose McGowan (12750).jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/2/28/Rose_McGowan_%2812'
         '750%29.jpg'),
        4118, 3176, '3cde47e6a83801f792b5419be1b7796819bafb92de9bd1a9f1eb91170615c667',
        6720843, 'CC BY-SA 4.0', 'Rhododendrites',
        (0.28992, 0.11794, 0.16124, 0.2867)),
    Ritratto(
        'File:AGH Berlin 10-2013 img13 Heidi Kosche.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/d/d2/AGH_Berlin_10-2013'
         '_img13_Heidi_Kosche.jpg'),
        3320, 4800, '09ccefcdc17d4b2959b5b37eb24a4efb0a7985e96e2fe3b6ebd7e18e4a93ff8e',
        4750070, 'CC BY-SA 3.0', 'A.Savin',
        (0.3439, 0.15133, 0.35672, 0.34006)),
    Ritratto(
        'File:Viennale 2018 Suspiria 14 Tilda Swinton.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/c/ca/Viennale_2018_Susp'
         'iria_14_Tilda_Swinton.jpg'),
        5700, 3800, 'e6928161e87ed20e0c4896377aa24db08c8fb35368c8bcc16571b1f478bf2de0',
        5217354, 'CC BY-SA 4.0', 'Manfred Werner - Tsui',
        (0.39121, 0.15673, 0.14627, 0.29839)),
    Ritratto(
        'File:L’aupaire Rocken am Brocken 2016 10.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/b/bb/L%E2%80%99aupaire_'
         'Rocken_am_Brocken_2016_10.jpg'),
        3648, 5472, '423d87e9d9a6bbcaab19fd9037b515bbf9ba7764e4fa5c521465366a2bdae333',
        6215575, 'CC BY-SA 4.0', 'S. Bollmann',
        (0.36225, 0.07706, 0.22961, 0.21806)),
    Ritratto(
        'File:Bardentreffen 2014 Sa 0991.JPG',
        ('https://upload.wikimedia.org/wikipedia/commons/2/2d/Bardentreffen_2014'
         '_Sa_0991.JPG'),
        4288, 2848, '518295cc2702c4756aac872bcc5d480c954b19e340d95e562256f4612dabdae0',
        3509008, 'CC BY-SA 4.0', 'Rs-foto',
        (0.35749, 0.26492, 0.1706, 0.32315)),
    Ritratto(
        'File:20180602 FIFA Friendly Match Austria vs. Germany Rainer Pariasek 850 0540.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/9/9e/20180602_FIFA_Frie'
         'ndly_Match_Austria_vs._Germany_Rainer_Pariasek_850_0540.jpg'),
        4219, 6329, '31eaa88a0ddd3cac56442dea696a87003cdbf3eadbfadebb0a0f151e19d048a4',
        10715292, 'CC BY-SA 4.0', 'Granada',
        (0.17545, 0.12114, 0.60495, 0.56752)),
    Ritratto(
        'File:Wils Sabine 2014-02-04 2.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/2/2d/Wils_Sabine_2014-0'
         '2-04_2.jpg'),
        4987, 3324, 'f5c66dcd6b5bbcbf25fc5d3b5fe6a099dc530fd36a8126a0f5b0a317d7282a23',
        5382868, 'CC BY-SA 3.0', 'Isiwal',
        (0.44676, 0.15794, 0.21602, 0.43179)),
    Ritratto(
        'File:Justyna Kulikowska, Stará Aréna 2025 (7).jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/f/f4/Justyna_Kulikowska'
         '%2C_Star%C3%A1_Ar%C3%A9na_2025_%287%29.jpg'),
        4867, 3245, 'd7f880ca416f53d5812d46d9654089b4230fe3f23729ad042a641e639a90f0e0',
        12820615, 'CC BY-SA 4.0', 'Tadeáš Bednarz',
        (0.53478, 0.18436, 0.1418, 0.27612)),
    Ritratto(
        'File:Robinhunicke at thatgamecompany photoshoot, August 2009.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/e/e7/Robinhunicke_at_th'
         'atgamecompany_photoshoot%2C_August_2009.jpg'),
        4256, 2832, '577ff35eceeaa591a5657f6fd7288a4f473a5fa5014bdbd7c5088733205563ce',
        9258205, 'CC BY-SA 2.0', 'Charlie Chu',
        (0.34796, 0.19527, 0.32592, 0.6993)),
    Ritratto(
        ('File:Österreichischer Filmpreis 2017 photo call Egon Schiele Tod und M'
         'ädchen Valerie Pachner 2.jpg'),
        ('https://upload.wikimedia.org/wikipedia/commons/8/8f/%C3%96sterreichisc'
         'her_Filmpreis_2017_photo_call_Egon_Schiele_Tod_und_M%C3%A4dchen_Valeri'
         'e_Pachner_2.jpg'),
        5471, 3647, 'c059475fe23a10f28ce2b15ad89bd83dd8134a6315b2e45ea52969376ead633c',
        11258143, 'CC BY-SA 4.0', 'Manfred Werner (Tsui)',
        (0.37227, 0.14632, 0.24118, 0.46453)),
    Ritratto(
        'File:Bélier Sandrine 2014-02-06 1.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/7/75/B%C3%A9lier_Sandri'
         'ne_2014-02-06_1.jpg'),
        6000, 4000, '61412466526c4abebbb9fcd2df1a28b34b59824dd06c38888cacdf7bcc57a380',
        4200069, 'CC BY-SA 3.0', 'Isiwal',
        (0.28897, 0.27114, 0.27028, 0.54401)),
    Ritratto(
        ('File:Judith McNamara speaking at an Adelaide University law lecture, M'
         'ay 2026 (028A4797).jpg'),
        ('https://upload.wikimedia.org/wikipedia/commons/d/d7/Judith_McNamara_sp'
         'eaking_at_an_Adelaide_University_law_lecture%2C_May_2026_%28028A4797%2'
         '9.jpg'),
        4569, 6853, 'bad64022e19ac50c5389c9537f916d1ac66e7ea6e31805a1e6cdb390904f0145',
        9095173, 'CC BY-SA 4.0', 'Yu Chu Chin',
        (0.34014, 0.21381, 0.33084, 0.28551)),
    Ritratto(
        'File:Frédérique Lantieri.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/0/05/Fr%C3%A9d%C3%A9riq'
         'ue_Lantieri.jpg'),
        3056, 4592, 'b2a444ac60599ba6ea50dfe5f45114077f115a747909b753a6b39cae344c1931',
        11032692, 'CC0', 'Jebulon',
        (0.19098, 0.18912, 0.49809, 0.46104)),
    Ritratto(
        'File:Violetta Parisini mit Band - Schwendermarkt Grätzlfest 2018 34.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/d/d1/Violetta_Parisini_'
         'mit_Band_-_Schwendermarkt_Gr%C3%A4tzlfest_2018_34.jpg'),
        4000, 5600, '80297cfa74908a1ea1c2e350680d801d19686680b9199e1ea00b081e73d453e6',
        5188544, 'CC BY-SA 4.0', 'Manfred Werner (Tsui)',
        (0.3428, 0.16856, 0.21646, 0.20994)),
    Ritratto(
        'File:Semporna Sabah Malaysia Igal-Dancer-01.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/b/ba/Semporna_Sabah_Mal'
         'aysia_Igal-Dancer-01.jpg'),
        3301, 4951, '30ad7b1a502cfb2ce3cf3e8e6a5dcfd4802c3be52f69e47bc0c2101d6518f2c9',
        7612748, 'CC BY-SA 3.0', 'CEphoto, Uwe Aranas',
        (0.38746, 0.15874, 0.18361, 0.14799)),
    Ritratto(
        'File:Wolfgang Sobotka 23-05-2013 01.JPG',
        ('https://upload.wikimedia.org/wikipedia/commons/9/96/Wolfgang_Sobotka_2'
         '3-05-2013_01.JPG'),
        4232, 2848, '67067e27e5aa1ddafddf2d461983ead58c1d3640b6086d29e3bc1519916bb938',
        4578628, 'CC BY-SA 3.0 at', 'Michael Kranewitter',
        (0.50146, 0.14128, 0.23647, 0.47897)),
    Ritratto(
        'File:Wikiměsto Týn nad Vltavou participants (2021-09-19) 01.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/b/b2/Wikim%C4%9Bsto_T%C'
         '3%BDn_nad_Vltavou_participants_%282021-09-19%29_01.jpg'),
        4353, 2902, '8e3cce73d86c581a0005f65c85d96f16f2dc90ae149f1dbda963ab040e854fdc',
        6160929, 'CC BY-SA 4.0', 'Tadeáš Bednarz',
        (0.36511, 0.27417, 0.15368, 0.29233)),
    Ritratto(
        'File:Critérium du Dauphiné 2014 - Etape 6 - Alberto Contador.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/b/b3/Crit%C3%A9rium_du_'
         'Dauphin%C3%A9_2014_-_Etape_6_-_Alberto_Contador.jpg'),
        3187, 4781, 'cc9a60f534c71e5346fcdf511a8fbb30646756b040d328e7c98b7f52507aa359',
        8545721, 'CC BY-SA 3.0', 'Ludovic Péron',
        (0.39972, 0.25918, 0.19174, 0.17713)),
    Ritratto(
        'File:Annkathrin Kammeyer IMG 3337 edit.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/d/d3/Annkathrin_Kammeye'
         'r_IMG_3337_edit.jpg'),
        3544, 5116, '2691f27b801a2ace694983013991b94c3e5bfc91505553bb1132e68b768eb41c',
        9265541, 'CC0', 'Christoph Braun',
        (0.30473, 0.18426, 0.44926, 0.42226)),
    Ritratto(
        'File:21st-century portrait photographs of sitting men.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/2/2c/21st-century_portr'
         'ait_photographs_of_sitting_men.jpg'),
        3000, 4500, 'c7ed05c6345ac6f3fe1bffe9e2f719d195695e692e258508c90c23c516e0967f',
        8041445, 'CC BY-SA 4.0', 'Dmitry Makeev',
        (0.33329, 0.07519, 0.29718, 0.25434)),
    Ritratto(
        'File:Bernardo Penabade.003 - Burela.jpg',
        ('https://upload.wikimedia.org/wikipedia/commons/0/07/Bernardo_Penabade.'
         '003_-_Burela.jpg'),
        5884, 4000, '3411c22f7013c0484553fcd7ae28638875987b03778ebc170e942718c81becf6',
        8023150, 'CC BY-SA 4.0', 'Fernando Losada Rodríguez',
        (0.40113, 0.08859, 0.19223, 0.39891)),
    Ritratto(
        'File:Bonna Mirza (5).jpg',
        'https://upload.wikimedia.org/wikipedia/commons/a/ac/Bonna_Mirza_%285%29.jpg',
        6000, 4000, '3b6113357797ad36697c6c43da80f944329fd2bf61445d1d9ff57cba1812c7b0',
        9099589, 'CC BY-SA 4.0', 'Nurunnaby Chowdhury (Hasive)',
        (0.34279, 0.22892, 0.26563, 0.48097)),
    Ritratto(
        'File:Ed Walsh portrait 1911.jpg',
        'https://upload.wikimedia.org/wikipedia/commons/b/b7/Ed_Walsh_portrait_1911.jpg',
        4788, 3300, '56a2f13236d4799ee3af535b4c9fc8016a558d4501edb5850d780fc4e3e90d7f',
        8783974, 'Public domain', 'Paul Thompson',
        (0.36492, 0.23653, 0.25458, 0.52067)),
)

__all__ = ["RITRATTI", "NITIDO", "NITIDO_BYTE", "NITIDO_SHA256", "PESI_LICENZA", "PESI_REPO",
           "PESI_REVISIONE", "Ritratto", "VAE", "VAE_SHA256"]
