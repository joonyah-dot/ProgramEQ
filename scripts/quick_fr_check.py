import argparse
import pathlib

import fr_analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", required=True)
    parser.add_argument("--wet", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    analysis = fr_analysis.analyze_frequency_response_files(pathlib.Path(args.dry), pathlib.Path(args.wet))
    frequencies = analysis["frequenciesHz"]
    magnitude_db = analysis["magnitudeDb"]
    points = analysis["pointsDb"]

    for label, value in points.items():
        print(f"{label}: {value:.2f} dB")

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".json":
        fr_analysis.write_metrics_json(out_path, analysis)
    else:
        fr_analysis.save_plot(out_path, frequencies, magnitude_db)


if __name__ == "__main__":
    main()
