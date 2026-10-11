# Privacy

[← Back](../../README.md) · [Italiano](../it/privacy.md)

**Short version:** your photos, videos, labels, categories and the names of
the people in them stay on your computer. They are never sent to the author,
to GitHub, to the model makers or to anyone else.

## What stays on your computer

- your photos and videos, which the program reads but never changes, moves or
  copies elsewhere;
- the library: thumbnails, fingerprints, labels, the category tree, faces and
  names;
- the AI models, once downloaded;
- your Hugging Face key, if you give one. It is kept in the Windows
  *Credential Manager*, never in a file.

There are no accounts, no analytics, no crash reports sent anywhere and no
advertising.

## When the program connects to the internet

| When | Where | What is sent | What for |
|---|---|---|---|
| first start | `pypi.org`, `download.pytorch.org` | a normal download request | download the AI engines |
| when you click the button | `huggingface.co` | a download request, plus your key if the model needs one | download an AI model |
| at start-up | `api.github.com` | a request for the list of versions | check for a new version |
| when updating | `github.com` | a download request | download the new version |

As with any download, these services can see your IP address and that
someone downloaded their files. None of these requests contains anything
about your photos.

Once the engines and models are in place, you can work with the network
cable unplugged.

## The encrypted vault

If you turn on the vault (*forziere*), the whole library is encrypted with
your password: without it, what is on disk is just noise. The original photos
stay outside the vault, where they were.

**If you lose the password, nobody can recover the library.** Not even the
author: there is no "forgot password", because any way back in would also be
a way in for someone else. Write the password down on paper and keep it
somewhere safe. The original photos are outside the vault, so they are never
lost.

## The two computers and the phone

Moving your work to another PC, or preparing the package for the phone,
always goes through a folder that **you** copy, for example on a USB stick.
No work or package ever travels over the network. The phone package is
encrypted file by file.

## Access from your home network

The window talks to a small server running inside the program, which by
default answers **only to your own computer**. In **Impostazioni** (Settings)
you can let other devices on your home network see the library too; even then
it answers only to the devices you approve one by one. It is off unless you
turn it on.
