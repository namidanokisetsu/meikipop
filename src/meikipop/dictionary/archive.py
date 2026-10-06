"""Read dictionary ZIPs with advisory CRCs and strict decompression/JSON checks."""
import zipfile


class DictionaryArchive(zipfile.ZipFile):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checksum_warnings = set()

    def open(self, name, mode="r", pwd=None, *, force_zip64=False):
        stream = super().open(name, mode, pwd, force_zip64=force_zip64)
        if mode == "r":
            update_crc = stream._update_crc
            filename = name.filename if isinstance(name, zipfile.ZipInfo) else name

            def advisory_crc(data):
                try:
                    update_crc(data)
                except zipfile.BadZipFile as error:
                    if not str(error).startswith("Bad CRC-32 for file "):
                        raise
                    self.checksum_warnings.add(filename)

            # Only this reader relaxes CRC metadata. Truncation, encryption and
            # decompression errors still propagate; callers validate parsed rows.
            stream._update_crc = advisory_crc
        return stream
