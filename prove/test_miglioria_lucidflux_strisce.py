import pytest

from officina.miglioria import lucidflux_strisce

torch = pytest.importorskip("torch")
nn = torch.nn


def _swish(x):
    return x * torch.sigmoid(x)


class _Resnet(nn.Module):
    def __init__(self, entra, esce):
        super().__init__()
        self.in_channels, self.out_channels = entra, esce
        self.norm1 = nn.GroupNorm(4, entra, eps=1e-6)
        self.conv1 = nn.Conv2d(entra, esce, 3, padding=1)
        self.norm2 = nn.GroupNorm(4, esce, eps=1e-6)
        self.conv2 = nn.Conv2d(esce, esce, 3, padding=1)
        if entra != esce:
            self.nin_shortcut = nn.Conv2d(entra, esce, 1)

    def forward(self, x):
        h = self.conv2(_swish(self.norm2(self.conv1(_swish(self.norm1(x))))))
        if self.in_channels != self.out_channels:
            x = self.nin_shortcut(x)
        return x + h


class _Su(nn.Module):
    def __init__(self, canali):
        super().__init__()
        self.conv = nn.Conv2d(canali, canali, 3, padding=1)

    def forward(self, x):
        return self.conv(nn.functional.interpolate(x, scale_factor=2.0, mode="nearest"))


class _Nulla(nn.Module):
    def forward(self, x):
        return x


class _Decoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.num_resolutions = 2
        self.ffactor = 2
        self.conv_in = nn.Conv2d(4, 16, 3, padding=1)
        self.mid = nn.Module()
        self.mid.block_1 = _Resnet(16, 16)
        self.mid.attn_1 = _Nulla()
        self.mid.block_2 = _Resnet(16, 16)
        alto, basso = nn.Module(), nn.Module()
        alto.block = nn.ModuleList([_Resnet(16, 16), _Resnet(16, 16)])
        alto.attn = nn.ModuleList()
        alto.upsample = _Su(16)
        basso.block = nn.ModuleList([_Resnet(16, 8), _Resnet(8, 8)])
        basso.attn = nn.ModuleList()
        self.up = nn.ModuleList([basso, alto])
        self.norm_out = nn.GroupNorm(4, 8, eps=1e-6)
        self.conv_out = nn.Conv2d(8, 3, 3, padding=1)

    def forward(self, z):
        h = self.mid.block_2(self.mid.attn_1(self.mid.block_1(self.conv_in(z))))
        for livello in reversed(range(self.num_resolutions)):
            for blocco in self.up[livello].block:
                h = blocco(h)
            if livello != 0:
                h = self.up[livello].upsample(h)
        return self.conv_out(_swish(self.norm_out(h)))


class _Ae(nn.Module):
    scale_factor = 0.3611
    shift_factor = 0.1159

    def __init__(self):
        super().__init__()
        self.decoder = _Decoder()

    def decode(self, z):
        return self.decoder(z / self.scale_factor + self.shift_factor)


@pytest.mark.parametrize("larga,alta,righe", [(11, 7, 1), (11, 7, 3), (12, 9, 5),
                                              (9, 13, 100), (16, 16, None)])
def test_a_strisce_come_intero(larga, alta, righe):
    torch.manual_seed(larga * 100 + alta)
    ae = _Ae().eval()
    with torch.no_grad():
        for nome, parte in ae.named_parameters():
            if "norm" in nome:
                parte.add_(0.3 * torch.randn_like(parte))
    z = torch.randn(1, 4, alta, larga) * 1.5
    with torch.no_grad():
        vero = ae.decode(z)
        mio = lucidflux_strisce.decodifica(ae, z, righe)
    assert mio.shape == vero.shape
    assert float((vero - mio).abs().max()) <= 1e-5 * max(1.0, float(vero.abs().max()))


def test_righe_per_larghezza():
    assert lucidflux_strisce.righe_per(2560) == 2 ** 18 // 2560
    assert lucidflux_strisce.righe_per(10 ** 9) == lucidflux_strisce.RIGHE_MINIME
    assert lucidflux_strisce.righe_per(0) == 2 ** 18
