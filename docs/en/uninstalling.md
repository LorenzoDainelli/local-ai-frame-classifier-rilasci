# Uninstalling

[← Back](../../README.md) · [Italiano](../it/disinstallazione.md)

## Remove the program

1. Close Local AI Frame Classifier.
2. Open **Windows Settings → Apps → Installed apps**.
3. Find **Local AI Frame Classifier**, click **⋯** and choose **Uninstall**.

The program, its Python and its libraries are removed.

## What stays, and why

Your **library stays**: labels, categories, thumbnails, faces, the AI engines
and the models you downloaded. This is deliberate, because it means a
reinstall finds everything as you left it and doesn't download gigabytes
again.

Your **photos** were never touched and stay where they have always been.

## Removing everything

To delete the library too, delete this folder after uninstalling:

```
%LOCALAPPDATA%\Local AI Frame Classifier
```

You can paste that line into the File Explorer address bar. **This cannot be
undone**: labels and categories are lost for good. The photos themselves are
not in that folder and are not affected.
