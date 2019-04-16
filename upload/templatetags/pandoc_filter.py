# --------------------------------------------------------------------
import os
import django
import django.template.defaultfilters as defaultfilters

import pypandoc

# --------------------------------------------------------------------
register = django.template.Library()

# --------------------------------------------------------------------
ROOT = os.path.dirname(__file__)

# --------------------------------------------------------------------
def pandoc_gen(value, template):
    template = os.path.join(ROOT, template + '.html')

    args = dict(
        to         = 'html5+smart+markdown_in_html_blocks',
        format     = 'md',
        extra_args = [
            '--base-header-level=2',
            '--mathjax', '--standalone',
            '--toc', '--toc-depth=4',
            '--template=%s' % (template,),
        ]
    )

    return pypandoc.convert_text(value, **args)

# --------------------------------------------------------------------
@register.filter()
@defaultfilters.stringfilter
def pandoc(value):
    return pandoc_gen(value, 'contents')

# --------------------------------------------------------------------
@register.filter()
@defaultfilters.stringfilter
def pandoc_prelude(value):
    return pandoc_gen(value, 'header')
