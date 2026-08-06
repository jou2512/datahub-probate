"""Macht `ui/` zum Paket, damit `from ui.serve import ...` funktioniert --
sonst findet weder pytest noch `python -m ui.serve` den Proxy-Server."""
