# Installation

[← Back](../../README.md) · [Italiano](../it/installazione.md)

## Before you start

- Windows 10 (version 1809 or later) or Windows 11, 64-bit.
- About 2 GB of free disk space, or about 6 GB with an NVIDIA graphics card,
  plus the space for the AI models you decide to download.
- An internet connection for the first start.

An NVIDIA card is optional. Without one the program uses the processor, which
is slower but gives the same results.

## Install

1. Download the latest installer: **[local-ai-frame-classifier-2.0.0-beta.14.exe](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases/download/v2.0.0-beta.14/local-ai-frame-classifier-2.0.0-beta.14.exe)**.
   Older versions are on the [releases page](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases).
2. Double-click the file.
3. Windows may show **"Windows protected your PC"**. This happens because the
   installer is not digitally signed yet, not because something is wrong.
   Click **More info**, then **Run anyway**.
4. Choose whether you want an icon on the desktop, then click **Install**.
   The program is installed for your user only, so it never asks for an
   administrator password.

## The first start

Open **Local AI Frame Classifier** from the Start menu.

1. A small window checks your computer and prepares the **AI engines** that
   suit it: about 2.7 GB to download with an NVIDIA card, about 0.5 GB
   without. This happens once. You can keep the window open and do something
   else meanwhile.
2. It asks for a **Hugging Face key**. It is optional: you only need it for
   the few models whose authors require one. You can skip it and add it
   later from **Impostazioni** (Settings).
3. The main window opens with a short guided tour: what the program does and
   doesn't do, which folder your photos are in, and the first import. See
   [First steps](first-steps.md).

## Checking the download

Every release also contains a `.sha256` file with the fingerprint of the
installer. To compare it, open PowerShell in the download folder and run:

```powershell
Get-FileHash .\local-ai-frame-classifier-2.0.0-beta.14.exe
```

The value must match the one in the `.sha256` file. This step is optional:
the program checks the fingerprint of every update on its own.

## Something went wrong?

- **The installer says the program is already running.** Close Local AI Frame
  Classifier and start the installer again.
- **The first start stopped while downloading the engines.** Check your
  connection and open the program again: it starts the download again.
- Anything else: see the [FAQ](faq.md) or
  [open an issue](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/issues/new/choose).
