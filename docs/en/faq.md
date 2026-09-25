# Frequently asked questions

[← Back](../../README.md) · [Italiano](../it/domande.md)

### Will it change, move or delete my photos?

No. The program only reads them. Thumbnails, labels and everything else it
produces go into its own library folder. You can even reorganise your folders
later: every file is recognised by its content, not by its path.

### Which files does it read?

Photos in HEIC/HEIF, JPEG, PNG, TIFF, WebP, AVIF, BMP and GIF; videos in MOV,
MP4, M4V, AVI, MKV, 3GP and WebM. Live Photos are paired with their video
automatically.

### Why does Windows say "Windows protected your PC"?

Because the installer is not digitally signed yet. Click **More info → Run anyway**. You can check
that the file is the original one with its `.sha256` fingerprint (see
[Installation](installation.md#checking-the-download)).

### Do I need an NVIDIA graphics card?

No. With an NVIDIA card the heavy work is much faster; without one the
processor does it, more slowly, with the same results. The program detects
the card on its own.

### Does it work offline?

Yes, once the first start is done and the models you want are downloaded.
Without a connection it simply doesn't look for updates.

### Is the interface available in English?

Not yet: today it is in Italian. The [First steps](first-steps.md) guide
translates every screen and menu.

### Does it recognise objects out of the box?

It learns **your** categories from **your** examples. You decide the tree
(for example *Holidays → Beach*), label a few shots, and the program starts
suggesting. The more you confirm, the better it gets, and the report card
(*La pagella*) shows exactly how well it is doing on your photos.

### What is the Hugging Face key for?

A few AI models can only be downloaded after accepting their authors'
conditions on huggingface.co, and the key proves you did. It is optional,
it is stored in the Windows Credential Manager and it is used only to
download those models.

### Can I use it on two computers?

Yes. From **Due computer** (Two computers) you prepare a folder with only
what the other PC hasn't seen yet, copy it on a USB stick and apply it on the
other side. Nothing travels over the network.

### Is there a phone app?

It is in development. The PC side is ready: **Telefono** (Phone) already
prepares the encrypted package the app will read.

### I found a bug. How do I report it?

[Open an issue](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/issues/new/choose) and write the version number
(it is in **Impostazioni**), what you did and what happened. **Never attach
your personal photos**, and don't write the names of people or categories
from your library.
