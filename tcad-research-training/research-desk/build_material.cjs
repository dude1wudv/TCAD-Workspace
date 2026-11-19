const path = require('node:path');
const dependencies = path.resolve(__dirname, '../../xjtu-shop-site/node_modules');
const esbuild = require(path.join(dependencies, 'esbuild'));
esbuild.buildSync({
  stdin: {
    contents: ['button/filled-button', 'button/text-button', 'button/filled-tonal-button',
      'textfield/filled-text-field', 'chips/assist-chip', 'chips/filter-chip',
      'tabs/tabs', 'tabs/primary-tab', 'labs/card/elevated-card', 'labs/card/outlined-card',
      'slider/slider', 'divider/divider', 'menu/menu', 'menu/menu-item',
      'iconbutton/filled-icon-button'].map(
      name => `import '@material/web/${name}.js';`
    ).join('\n'),
    resolveDir: path.dirname(dependencies),
  },
  nodePaths: [dependencies],
  bundle: true,
  minify: true,
  format: 'iife',
  legalComments: 'eof',
  outfile: path.join(__dirname, 'material.bundle.js'),
});
