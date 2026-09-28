/**
 * Offline adapter around the vendored Trazor centreline pipeline.
 *
 * This only produces SVG and metadata.  It never imports the Piper SDK and
 * therefore cannot cause robot motion.
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { PNG } from 'pngjs'
import { vectorize } from '@trazor/engine'
import { getProfile, normalizeSettings } from '@trazor/core'

async function main(): Promise<void> {
  const [inputPath, outputPath] = process.argv.slice(2)
  if (!inputPath || !outputPath) {
    throw new Error('usage: trazor_centerline_runner.ts INPUT.png OUTPUT.svg')
  }
  const decoded = PNG.sync.read(readFileSync(resolve(inputPath)))
  const image = {
    width: decoded.width,
    height: decoded.height,
    data: new Uint8ClampedArray(decoded.data),
  }
  const envNumber = (name: string, fallback: number) => {
    const value = Number(process.env[name])
    return Number.isFinite(value) ? value : fallback
  }
  const settings = normalizeSettings({
  ...getProfile('pen-plotter').patch,
  // Preserve short facial/stripe marks, while deleting isolated raster specks.
  maxDimension: envNumber('TRAZOR_MAX_DIMENSION', 1536),
  pruneLength: envNumber('TRAZOR_PRUNE_LENGTH', 5),
  smoothing: envNumber('TRAZOR_SMOOTHING', 0.58),
  fitTolerance: envNumber('TRAZOR_FIT_TOLERANCE', 1.1),
  simplifyTolerance: envNumber('TRAZOR_SIMPLIFY_TOLERANCE', 0.35),
  curveOptimize: true,
  optTolerance: 0.28,
  unit: 'px',
  precision: 2,
  svgTitle: 'Tiger reference — Trazor centreline candidate',
  })
  const result = await vectorize(image, settings, undefined, { withDocument: true })
  mkdirSync(dirname(resolve(outputPath)), { recursive: true })
  writeFileSync(resolve(outputPath), result.svg, 'utf8')
  writeFileSync(`${resolve(outputPath)}.json`, JSON.stringify({
  source: resolve(inputPath),
  settings,
  stats: result.stats,
  warnings: result.warnings,
  }, null, 2), 'utf8')
  writeFileSync(`${resolve(outputPath)}.document.json`, JSON.stringify(result.document, null, 2), 'utf8')
  console.log(JSON.stringify({
  output: resolve(outputPath),
  stats: result.stats,
  warnings: result.warnings,
  }, null, 2))
}

void main()
