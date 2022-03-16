# Multipart parser

BáiZé provides a "bring your own I/O" multipart parser with excellent performance.

## Example

```python
from baize import multipart

parser = multipart.MultipartDecoder(
   content_type.options["boundary"].encode("latin-1"), charset
)
field_name = ""
data = bytearray()
file: Optional[UploadFile] = None

items: List[Tuple[str, Union[str, UploadFile]]] = []

for chunk in stream:
   parser.receive_data(chunk)
   while True:
      event = parser.next_event()
      if isinstance(event, (multipart.Epilogue, multipart.NeedData)):
         break
      elif isinstance(event, multipart.Field):
         field_name = event.name
      elif isinstance(event, multipart.File):
         field_name = event.name
         file = UploadFile(
               event.filename, event.headers.get("content-type", "")
         )
      elif isinstance(event, multipart.Data):
         if file is None:
               data.extend(event.data)
         else:
               file.write(event.data)

         if not event.more_data:
               if file is None:
                  items.append(
                     (field_name, multipart.safe_decode(data, charset))
                  )
                  data.clear()
               else:
                  file.seek(0)
                  items.append((field_name, file))
                  file = None
```
