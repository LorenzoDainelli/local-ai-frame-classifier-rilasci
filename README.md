# Local AI Frame Classifier

**Sort your photos and videos with AI, entirely on your own computer.**

**[⬇ Download for Windows](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases/download/v2.0.0-beta.12/local-ai-frame-classifier-2.0.0-beta.12.exe)** · version 2.0.0-beta.12 · 38 MB ·
[all versions](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases) · **[Italiano](README.it.md)**

> **Beta.** The program works and updates itself, but it is still being
> tested. The interface is in **Italian**; these guides explain every
> screen in English.

---

## Why

Most photo organisers upload your pictures to someone else's server before
they can recognise anything in them. This one doesn't. The AI models run on
your PC, your library stays on your disk, and nothing you label ever leaves
your computer.

## What it does

- **Imports photos and videos** (HEIC, JPEG, PNG, MOV, MP4 and more) and **never touches
  the originals**. It spots duplicates, pairs Live Photos with their video and
  reads the real date of every shot, time zone included.
- **Learns your own categories.** You build the tree of categories; the
  program studies the shots you have confirmed and suggests labels for the
  rest, always showing *why*: "it looks like these five you already labelled".
- **Fast labelling** from the keyboard, one shot after another, without the
  page ever reloading.
- **Finds faces** and groups the similar ones, so you name people one group at
  a time.
- **Searches by words**, with a language model that also runs locally.
- **Tells you where you stand**: how much is labelled, how often the
  suggestions are right on *your* photos, and what is worth labelling next.
- **Optional encrypted vault**: without the password, the library on disk is
  just noise.
- **Two computers**: carry your work from one PC to the other on a USB stick.
  Nothing travels over the network.
- **Uses an NVIDIA graphics card** when there is one, and works without it.
- **Updates itself.**

A companion **phone app**, which will show your library offline, is in
development.

## Install in three steps

1. **[Download the installer](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/releases/download/v2.0.0-beta.12/local-ai-frame-classifier-2.0.0-beta.12.exe)** (38 MB).
2. Double-click it. Windows may say *"Windows protected your PC"* because the
   file is not signed yet: click **More info → Run anyway**.
3. Open **Local AI Frame Classifier** from the Start menu. On the first start
   it prepares its AI engines for your hardware (a download of about 0.5 GB,
   or 2.7 GB with an NVIDIA card) and then guides you through choosing your
   photo folder.

No administrator password, no Python, no command prompt.
[Full installation guide →](docs/en/installation.md)

## Requirements

| | |
|---|---|
| System | Windows 10 (1809 or later) or Windows 11, 64-bit |
| Graphics card | optional; NVIDIA cards are used automatically |
| Disk space | about 2 GB, or 6 GB with an NVIDIA card, plus the models you choose |
| Internet | on the first start, and to download models; afterwards it works offline |

## Your privacy

Photos, videos, labels, categories and names **never leave your computer**.
The program connects to the internet only for these four things, and none of
them carries your data:

| When | Where | What for |
|---|---|---|
| first start | `pypi.org`, `download.pytorch.org` | download the AI engines |
| when you click the button | `huggingface.co` | download the AI models |
| at start-up | `api.github.com` | check for a new version |
| when updating | `github.com` | download the new version |

[Privacy in detail →](docs/en/privacy.md)

## Guides

- [Installation](docs/en/installation.md)
- [First steps](docs/en/first-steps.md)
- [Updates](docs/en/updates.md)
- [Privacy](docs/en/privacy.md)
- [Uninstalling](docs/en/uninstalling.md)
- [Frequently asked questions](docs/en/faq.md)

## Help and feedback

Found a bug or have an idea?
[Open an issue](https://github.com/LorenzoDainelli/local-ai-frame-classifier-rilasci/issues/new/choose). **Never attach your personal photos**,
and never include the names of people or categories from your library: a
description of what happened and the version number are enough.

To report a security problem privately, see [SECURITY.md](SECURITY.md).

## Licence

Copyright © 2026 Lorenzo Dainelli. All rights reserved. You may download and
use the program on your own computers; see [LICENSE.md](LICENSE.md).
The source code is not public.
