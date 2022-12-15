from anki.stats import CollectionStats

def csr_enabled(self: CollectionStats):
    return hasattr(self, "type_csr") and self.type_csr == True
