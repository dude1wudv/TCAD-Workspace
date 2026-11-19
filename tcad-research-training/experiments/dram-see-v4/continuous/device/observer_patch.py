"""Apply an evidence-driven observer repair to copied candidate decks only."""

FAILURE_RUN = '20261017T042419Z-v4-continuous-b1-d2-r3'
PATCH_ID = 'contact-bounds-from-native-mesh-r2'


def apply(text, dimension):
    """Preserve CAD membership/measure; obtain contact bounds from native mesh.

The r3 execution log proved that bbox returned #f for a nonempty edge list.
Both bbox APIs are documented for entities/lists, but that path is unavailable
for the actual contact edge. The existing SVisual measurement plan already
measures every contact coordinate min/max from the original mesh. Do not
substitute nominal coordinates or keep retrying the failed CAD bbox APIs.
"""
    begin = '(define (s2-observe-contact name port)'
    end = '(define (s2-observe-contact-probe id name matches port)'
    if text.count(begin) != 1 or text.count(end) != 1 or '(bounds (bbox-exact entities))' not in text:
        raise ValueError('Observer template differs; preserve and inspect before patching')
    start = text.index(begin)
    finish = text.index(end, start)
    measure = 'edge:length' if dimension == 2 else 'face:area'
    unit = 'um' if dimension == 2 else 'um^2'
    replacement = '''; Native failure __FAILURE_RUN__: actual contact edges exist but bbox returns #f.
; SDE measures membership/count/length or area; SVisual measures original-mesh
; contact bounds with the unchanged coordinate measurements and tolerances.
(define (s2-observe-contact name port)
  (display "S2_CONTACT_BEGIN ") (write name) (newline)
  (let ((entities (s2-contact-entities name)))
    (display "S2_CONTACT_ENTITIES ") (write entities) (newline)
    (if (or (not (list? entities)) (null? entities))
      (sde:error (string-append "S2 contact query returned no entity list: " name))
      (let ((measure (apply + (map __MEASURE__ entities))))
        (display "S2_CONTACT_MEASURE ") (write measure) (newline)
        (s2-csv-row (list name (length entities) measure "__UNIT__") port)))))

'''.replace('__FAILURE_RUN__', FAILURE_RUN).replace('__MEASURE__', measure).replace('__UNIT__', unit)
    result = text[:start] + replacement + text[finish:]
    old_header = '(s2-csv-row (list "contact" "entity_count" "measure" "unit"\n      "min_x" "min_y" "min_z" "max_x" "max_y" "max_z") s2-contact-port)'
    if result.count(old_header) != 1:
        raise ValueError('Unexpected original SDE contact header')
    return result.replace(old_header, '(s2-csv-row (list "contact" "entity_count" "measure" "unit") s2-contact-port)')
