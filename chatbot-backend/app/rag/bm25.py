"""
app/rag/bm25.py — Implementación ligera de BM25 para Búsqueda Híbrida.
Permite realizar búsquedas por coincidencia exacta de palabras clave (lexical search),
ideal para siglas (AACSW), nombres propios y datos tabulares que los modelos
vectoriales suelen omitir.
"""

import math
from collections import Counter
import re
from typing import List, Dict, Any

class BM25Retriever:
    def __init__(self, docs: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        """
        docs: Lista de diccionarios, típicamente [{"page_content": "...", "metadata": {...}}, ...]
        """
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.doc_freqs = []
        self.idf = {}
        self.doc_len = []
        self.avgdl = 0

        self._initialize()

    def _tokenize(self, text: str) -> List[str]:
        # Tokenización simple: minúsculas y remoción de puntuación no esencial.
        # Soporta palabras con acentos y números.
        return [w.lower() for w in re.findall(r'\b\w+\b', text)]

    def _initialize(self):
        df = {}
        num_docs = len(self.docs)
        total_len = 0
        
        for doc in self.docs:
            content = doc.get("page_content", "") if isinstance(doc, dict) else str(doc)
            tokens = self._tokenize(content)
            self.doc_len.append(len(tokens))
            total_len += len(tokens)
            
            frequencies = Counter(tokens)
            self.doc_freqs.append(frequencies)
            
            for word in frequencies:
                df[word] = df.get(word, 0) + 1
                
        self.avgdl = total_len / num_docs if num_docs > 0 else 0
        
        for word, freq in df.items():
            # Formula IDF de BM25 (Okapi)
            self.idf[word] = math.log(1 + (num_docs - freq + 0.5) / (freq + 0.5))

    def get_scores(self, query: str) -> List[float]:
        """Calcula el score BM25 para cada documento respecto a la query."""
        tokens = self._tokenize(query)
        scores = [0.0] * len(self.docs)
        
        for i, doc_freq in enumerate(self.doc_freqs):
            score = 0.0
            doc_l = self.doc_len[i]
            for token in tokens:
                if token in doc_freq:
                    freq = doc_freq[token]
                    num = freq * (self.k1 + 1)
                    den = freq + self.k1 * (1 - self.b + self.b * doc_l / self.avgdl)
                    score += self.idf.get(token, 0) * (num / den)
            scores[i] = score
            
        return scores
