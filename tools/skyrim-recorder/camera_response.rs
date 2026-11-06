//! Experimental response-only candidates for issue #520. No solver eligibility is inferred.
//! Build with rustc; the engine is deliberately not linked or changed by this research tool.
use std::fmt::Write as _;
use std::io::{self, BufRead, Write};

#[derive(Clone, Copy)]
enum Model {
    Direct,
    Exponential { tau: f64 },
    Spring { base: f64, damping: f64 },
}

struct Response {
    position: f64,
    velocity: f64,
}

impl Response {
    fn at(position: f64) -> Self {
        Self {
            position,
            velocity: 0.0,
        }
    }

    fn advance(&mut self, model: Model, target: f64, dt: f64) -> f64 {
        let previous_delta = self.position - target;
        let correction = match model {
            Model::Direct => 0.0,
            Model::Exponential { tau } => previous_delta * (-dt / tau).exp(),
            Model::Spring { base, damping } => {
                base.powf(dt) * previous_delta + damping * dt * self.velocity
            }
        };
        self.position = target + correction;
        self.velocity = (correction - previous_delta) / dt;
        correction
    }
}

struct Sample {
    time: f64,
    dt: f64,
    player: f64,
    reference: f64,
}

fn load(path: &str) -> Result<Vec<Vec<Sample>>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut runs: Vec<Vec<Sample>> = Vec::new();
    for line in text.lines() {
        let fields: Vec<&str> = line.split('\t').collect();
        if fields.len() != 5 {
            return Err("expected run,time,game_dt,player,reference".into());
        }
        let run: usize = fields[0].parse().map_err(|_| "invalid run")?;
        let values: Vec<f64> = fields[1..]
            .iter()
            .map(|v| v.parse::<f64>())
            .collect::<Result<_, _>>()
            .map_err(|_| "invalid number")?;
        if values.iter().any(|v| !v.is_finite())
            || values[2].abs() > 100000.0
            || values[1] <= 0.0
            || values[1] > 0.1
        {
            return Err("invalid sample".into());
        }
        if run == runs.len() {
            runs.push(Vec::new());
        }
        if run + 1 != runs.len() {
            return Err("runs must be contiguous".into());
        }
        let samples = &mut runs[run];
        if samples.last().is_some_and(|s| values[0] <= s.time) {
            return Err("time reversed".into());
        }
        samples.push(Sample {
            time: values[0],
            dt: values[1],
            player: values[2],
            reference: values[3],
        });
    }
    if runs.is_empty() || runs.iter().any(|r| r.len() < 2) {
        return Err("empty trajectory".into());
    }
    Ok(runs)
}

fn evaluate(runs: &[Vec<Sample>], model: Model, curves: bool) -> Result<String, String> {
    let mut output = String::from("{\"runs\":[");
    for (index, run) in runs.iter().enumerate() {
        if index != 0 {
            output.push(',');
        }
        let mut response = Response::at(run[0].player);
        let mut square = 0.0_f64;
        let mut duration = 0.0_f64;
        let mut peak = 0.0_f64;
        let mut predictions = Vec::with_capacity(run.len());
        for (i, sample) in run.iter().enumerate() {
            let predicted = response.advance(model, sample.player, sample.dt);
            if !predicted.is_finite() {
                return Err("nonfinite response".into());
            }
            predictions.push(predicted);
            if sample.time >= 0.0 && i > 0 {
                let weight = sample.time - run[i - 1].time;
                let error = predicted - sample.reference;
                square += weight * error * error;
                duration += weight;
                peak = peak.max(error.abs());
            }
        }
        if duration <= 0.0 {
            return Err("no scored motion".into());
        }
        write!(
            output,
            "{{\"rmse\":{},\"peak\":{}",
            (square / duration).sqrt(),
            peak
        )
        .unwrap();
        if curves {
            output.push_str(",\"prediction\":[");
            for (i, value) in predictions.iter().enumerate() {
                if i != 0 {
                    output.push(',');
                }
                write!(output, "{value}").unwrap();
            }
            output.push(']');
        }
        output.push('}');
    }
    output.push_str("]}");
    Ok(output)
}

fn main() -> Result<(), String> {
    let path = std::env::args()
        .nth(1)
        .ok_or("usage: camera-response DATA.tsv")?;
    let runs = load(&path)?;
    let stdout = io::stdout();
    let mut output = stdout.lock();
    for line in io::stdin().lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        let args: Vec<&str> = line.split_whitespace().collect();
        if args.len() != 4 {
            return Err("expected model,parameter1,parameter2,curves".into());
        }
        let a: f64 = args[1].parse().map_err(|_| "invalid parameter")?;
        let b: f64 = args[2].parse().map_err(|_| "invalid parameter")?;
        let model = match args[0] {
            "direct" => Model::Direct,
            "exponential" if a.is_finite() && a > 0.0 && a <= 1.0 => Model::Exponential { tau: a },
            "spring"
                if a.is_finite()
                    && a > 0.0
                    && a < 1.0
                    && b.is_finite()
                    && (0.0..1.0).contains(&b) =>
            {
                Model::Spring {
                    base: a,
                    damping: b,
                }
            }
            _ => return Err("invalid model or parameters".into()),
        };
        writeln!(output, "{}", evaluate(&runs, model, args[3] == "1")?)
            .map_err(|e| e.to_string())?;
        output.flush().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn constant_target_stays_still_and_direct_follows_every_input() {
        for model in [
            Model::Direct,
            Model::Exponential { tau: 0.055 },
            Model::Spring {
                base: 0.001,
                damping: 0.6,
            },
        ] {
            let mut r = Response::at(120.0);
            for _ in 0..120 {
                assert_eq!(r.advance(model, 120.0, 1.0 / 60.0), 0.0);
            }
        }
        let mut r = Response::at(0.0);
        for y in [12.0, -4.0, 9000.0] {
            assert_eq!(r.advance(Model::Direct, y, 0.02), 0.0);
        }
    }
    #[test]
    fn exponential_settles_and_reversal_keeps_residual() {
        let m = Model::Exponential { tau: 0.055 };
        let mut r = Response::at(0.0);
        let first = r.advance(m, 12.0, 0.055);
        assert!((first + 12.0 / std::f64::consts::E).abs() < 1e-12);
        let old_position = r.position;
        let reverse = r.advance(m, 10.0, 1e-8);
        assert!((10.0 + reverse - old_position).abs() < 1e-5);
        for _ in 0..120 {
            r.advance(m, 10.0, 1.0 / 60.0);
        }
        assert!((r.position - 10.0).abs() < 1e-10);
    }
    #[test]
    fn spring_has_memory_and_returns_to_a_stationary_target() {
        let m = Model::Spring {
            base: 0.001,
            damping: 0.6,
        };
        let mut r = Response::at(0.0);
        let first = r.advance(m, 12.0, 1.0 / 60.0);
        assert!(first < -10.0 && first > -12.0);
        assert!(r.velocity > 0.0);
        for _ in 0..240 {
            r.advance(m, 12.0, 1.0 / 60.0);
        }
        assert!((r.position - 12.0).abs() < 1e-10);
        assert!(r.velocity.abs() < 1e-8);
    }
}
