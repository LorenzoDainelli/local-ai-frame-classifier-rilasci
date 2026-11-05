from __future__ import annotations


def edt_triton(dati):
    import cv2
    import numpy
    import torch

    piatti = dati.detach().to("cpu").numpy().astype(numpy.uint8)
    fuori = [cv2.distanceTransform(uno, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
             for uno in piatti]
    return torch.from_numpy(numpy.stack(fuori)).to(device=dati.device, dtype=torch.float32)


def connected_components_triton(ingresso):
    import cv2
    import numpy
    import torch

    forma = ingresso.shape
    piatti = ingresso.detach().reshape(-1, forma[-2], forma[-1]).to("cpu").numpy() != 0
    etichette, quante = [], []
    for uno in piatti:
        _, nomi, misure, _ = cv2.connectedComponentsWithStats(
            uno.astype(numpy.uint8), connectivity=8, ltype=cv2.CV_32S)
        grandezze = misure[:, cv2.CC_STAT_AREA].astype(numpy.int64)
        grandezze[0] = 0
        etichette.append(nomi.astype(numpy.int64))
        quante.append(grandezze[nomi])
    dove = ingresso.device
    return (torch.from_numpy(numpy.stack(etichette)).reshape(forma).to(dove),
            torch.from_numpy(numpy.stack(quante)).reshape(forma).to(dove))
