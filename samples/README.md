# samples

Drop source PDFs here for local testing. They are git-ignored (`samples/*.pdf`)
so real drawings are never committed.

Run the converter against a sample with:

```bash
ONSHAPE2PNPLTTR_SAMPLE=samples/Drawing.pdf python3 -m unittest discover -s tests
```

or simply:

```bash
make convert PDF=samples/Drawing.pdf OUT=samples/Drawing.pnplttr
```