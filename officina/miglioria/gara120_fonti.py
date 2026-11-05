from __future__ import annotations

SNU_REPO = "xypeng9903/SNU_FILM"
SNU_REVISIONE = "a02ce2ca387b56cb0a3633416480cb40898b813c"
SNU_LISTE = ("easy", "medium", "hard", "extreme")
SNU_LICENZA = "SNU-FILM (GOPRO cc-by-4.0, YouTube), solo per la gara"
IMPRONTA_CASI = "b5123116a5981e5866642dd2df2fd3b04017d31f054f2d155ec0762663033e75"
IMPRONTA_FILE = "01ca4e80d6d9d6158f529e8d2d6d815c5dbbe0e48bbefc6e1084058ad8644c6d"
CASI_SNU = 320
FILE_SNU = 1658
BYTE_SNU = 1616085584
IMPRONTA_TUTTI = "b2f7c45a69490e69300d34f8cab2335972361281dcbcf4fd81266eff25d36520"
FILE_TUTTI = 19337

XVFI_INDIRIZZO = ("https://www.dropbox.com/sh/duisote638etlv2/"
                  "AABJw5Vygk94AWjGM4Se0Goza?dl=1")
XVFI_BYTE = 19349348905
XVFI_LICENZA = "X-TEST e Adobe240 da XVFI: solo ricerca e studio"
DENTRO = {
    "encoded_test.tar.gz": (
        "6c0562613bfe3ae447b551c8582844775a1b7d1d51632fed876c3cba8b9655cf", 354340390),
    "Adobe240fps_test_spilt_XVFI.zip": (
        "82fbb541446c20f6dcf0c6dff895d5ae7e57c97a5446cae59816dee0ec300aa9", 2428073934),
}
XTEST_MP4 = {
    "Type1/TEST01_003_f0433":
        "dc2e7ed80b2d7cf4078ce6a5f868a1673cc9c4bd67ff3c4b9bc7caea50dbbd62",
    "Type1/TEST02_045_f0465":
        "dc51c02bf6216f8e656c4292babdd8eb51f5a6d9ba47a4bfc039d5c67632a5ba",
    "Type1/TEST03_081_f4833":
        "1ee3a161ac7f27da86339b602c3e5e73ca1546536b2102d02addae7ca5faf57d",
    "Type1/TEST04_140_f3889":
        "bad5aa616705844db57d6742b5bf7463b9f55dada5a592f402a090fd884feece",
    "Type1/TEST05_158_f0321":
        "ccf805a12184ff37b09a23f90fff08589f4dc75007578ffabb021d7c80c2bb0b",
    "Type2/TEST06_001_f0273":
        "a87ef43bf316735bd26710cae6bb82d31136f01dc79479da6ad1d6b97dfe61dc",
    "Type2/TEST07_076_f1889":
        "1cd4c76318d8fbf3d3f5f40dbab0e9eb9b8e028f19af3fae6f3dabf2b7ca1804",
    "Type2/TEST08_079_f0321":
        "8fa9c4030c0040279ba7b80d9a81985497bc50735faeb7848e214ac0e79a753f",
    "Type2/TEST09_112_f0177":
        "ac7c236fbe0f1ccad3a2e588239e1569f0332829db8705ebcf56d82e4f8c5b1a",
    "Type2/TEST10_172_f1905":
        "dfdca4e0c000d8f391c07ae342120ee2be705aeba6de66302d30c0426900a859",
    "Type3/TEST11_078_f4977":
        "1fb8632d80ecd7eb3b2a44ad10e77012d763dcaabb279e3c02d1d9a5652a34e0",
    "Type3/TEST12_087_f2721":
        "5547ec2c6d52e9a5f0a026dba93bef18ee036595b922aeb1f4ea86d4f1d72140",
    "Type3/TEST13_133_f4593":
        "b742957551b851593f39a4e998913a863b01874ea879caa45d321d91e57b8094",
    "Type3/TEST14_146_f1761":
        "8d24b7b096488066464745a7692acc431de9a686b2e24c9f21c7be25e0f11e5b",
    "Type3/TEST15_148_f0465":
        "36b60759ca2b6db17dc944d94bbcb706d8e641149bec1296035906728fa66d3f",
}
XTEST_CARTELLA = "encoded_test/"

__all__ = ["BYTE_SNU", "CASI_SNU", "DENTRO", "FILE_SNU", "FILE_TUTTI", "IMPRONTA_CASI",
           "IMPRONTA_FILE", "IMPRONTA_TUTTI",
           "SNU_LICENZA", "SNU_LISTE", "SNU_REPO", "SNU_REVISIONE", "XTEST_CARTELLA",
           "XTEST_MP4", "XVFI_BYTE", "XVFI_INDIRIZZO", "XVFI_LICENZA"]
