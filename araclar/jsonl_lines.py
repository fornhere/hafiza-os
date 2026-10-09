"""JSONL için yalnız fiziksel LF satır sınırları."""


def split_jsonl(text, keepends=False):
    # Unicode ayırıcılar JSON stringinin içeriğidir; yalnız son boş parçayı at.
    parts = text.split('\n')
    ended = parts[-1] == ''
    if ended: parts.pop()
    if keepends:
        # Yerel istemci hash'leri CRLF dahil özgün baytları kapsar.
        return [line + ('\n' if ended or i < len(parts)-1 else '')
                for i, line in enumerate(parts)]
    # Capture prefix hash'i geçmişte olduğu gibi CRLF'yi LF olarak birleştirir.
    return [line[:-1] if line.endswith('\r') else line for line in parts]
