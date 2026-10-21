# [Pycountry][pycountry-website] for Kodi 19+

Pycountry repacked for Kodi 19+.

Translations can be used via Python GNU [gettext][gettext-website] API:

```
import gettext
german = gettext.translation(
        "iso3166", pycountry.LOCALES_DIR, languages=["de"]
)
german.install()
assert _("Germany") == "Deutschland"
```

You can exclude the locales folder from your zip file and save some MBs if your addon doesn't make use of translations.


# 
#### [Pycountry][pycountry-website] is a Python library to access ISO country, subdivision, language, currency and script definitions and their translations.



[pycountry-website]: https://github.com/flyingcircusio/pycountry
[gettext-website]: https://docs.python.org/3/library/gettext.html


