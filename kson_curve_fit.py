"""Bounded-error quadratic Bezier compression of KSON laser samples."""
import math


def parameter(x, a):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    return x / (a + math.sqrt(max(0.0, a * a + (1 - 2 * a) * x)))


def curve(x, a, b):
    u = parameter(x, a)
    return 2 * b * u * (1 - u) + u * u


def value(point, outgoing=False):
    v = point[1]
    return v[-1 if outgoing else 0] if isinstance(v, list) else v


def fit_span(points):
    t0, t1 = points[0][0], points[-1][0]
    v0, v1 = value(points[0], True), value(points[-1])
    dv = v1 - v0
    xy = [((p[0] - t0) / (t1 - t0), (value(p) - v0) / dv)
          for p in points[1:-1]] if dv else []
    if not xy:
        return 0.5, 0.5

    def candidate(a):
        terms = [(parameter(x, a), y) for x, y in xy]
        den = sum((2*u*(1-u))**2 for u, _ in terms)
        b = max(0.0, min(1.0, sum(2*u*(1-u)*(y-u*u) for u, y in terms) / den))
        return sum((2*b*u*(1-u)+u*u-y)**2 for u, y in terms), a, b

    best = min(candidate(i / 20) for i in range(21))
    step = 0.05
    for _ in range(12):
        best = min(best, candidate(max(0.0, best[1]-step)),
                   candidate(min(1.0, best[1]+step)))
        step /= 2
    # Some editor versions evaluate x=0 through a formula dividing by 2*a-1.
    # a=.5 is mathematically valid but produces NaN there on curved edges.
    if best[1] == 0.5 and best[2] != 0.5:
        best = min(candidate(0.499999), candidate(0.500001))
    return best[1:]


def span_error(points, a, b):
    """Exact max deviation from each source linear segment, including interiors.

    Both Bezier coordinates are quadratic in u. Difference from a source
    line is quadratic too; its only interior extremum is the derivative root.
    """
    t0, t1 = points[0][0], points[-1][0]
    v0, dv = value(points[0], True), value(points[-1]) - value(points[0], True)
    worst = 0.0
    for left, right in zip(points, points[1:]):
        x0, x1 = (left[0]-t0)/(t1-t0), (right[0]-t0)/(t1-t0)
        y0, y1 = value(left, True), value(right)
        slope = (y1-y0)/(x1-x0)
        qa = dv*(1-2*b) - slope*(1-2*a)
        qb = 2*dv*b - 2*slope*a
        qc = v0-y0+slope*x0
        u0, u1 = parameter(x0, a), parameter(x1, a)
        probes = [u0, u1]
        if abs(qa) > 1e-15:
            root = -qb/(2*qa)
            if u0 < root < u1:
                probes.append(root)
        worst = max(worst, *(abs(qa*u*u+qb*u+qc) for u in probes))
    return worst


def simplify(points, tolerance):
    """Preserve jumps, extrema, plateau boundaries, and existing curve edges."""
    if tolerance == 0 or len(points) <= 2:
        return [p[:] for p in points], 0.0
    fixed = {0, len(points)-1}
    for i, p in enumerate(points):
        if isinstance(p[1], list):
            fixed.add(i)
        if len(p) == 3:
            fixed.update((i, min(i+1, len(points)-1)))
        if 0 < i < len(points)-1:
            incoming = value(p)-value(points[i-1], True)
            outgoing = value(points[i+1])-value(p, True)
            if incoming*outgoing < 0 or (incoming == 0) != (outgoing == 0):
                fixed.add(i)
    result = []
    max_error = 0.0
    boundaries = sorted(fixed)
    for lo, hi in zip(boundaries, boundaries[1:]):
        stack = [(lo, hi)]
        while stack:
            start, stop = stack.pop()
            if stop-start == 1:
                result.append(points[start][:])
                continue
            samples = points[start:stop+1]
            # Prefer a straight segment whenever it already meets the bound.
            a = b = 0.5
            error = span_error(samples, a, b)
            if error > tolerance:
                a, b = fit_span(samples)
                error = span_error(samples, a, b)
            if error <= tolerance:
                point = points[start][:2]
                if abs(a-b) > 1e-12:
                    point.append([a, b])
                result.append(point)
                max_error = max(max_error, error)
            else:
                middle = (start+stop)//2
                stack.extend([(middle, stop), (start, middle)])
    result.append(points[-1][:])
    return result, max_error


def smooth_sharp_runs(points, tolerance=0.002):
    """Replace tiny sharp-hack edges with freely fitted monotonic Bezier runs.

    Subdivide only when a whole run exceeds the sharp-specific error bound.
    All emitted edges stay curved (a != b), without fixed endpoint tangents.
    """
    if len(points) < 2:
        return points, 0.0, 0
    fixed = {0, len(points)-1}
    for i, p in enumerate(points):
        if isinstance(p[1], list):
            fixed.add(i)
        if 0 < i < len(points)-1:
            incoming = value(p)-value(points[i-1], True)
            outgoing = value(points[i+1])-value(p, True)
            if incoming*outgoing < 0 or (incoming == 0) != (outgoing == 0):
                fixed.add(i)
    result, worst, changed = [], 0.0, 0
    bounds = sorted(fixed)
    for lo, hi in zip(bounds, bounds[1:]):
        samples = points[lo:hi+1]
        start_sharp = len(samples[0]) == 3 and samples[0][2] == [0.0, 1.0]
        # A same-direction (obtuse) slam-to-curve connection also needs a
        # genuine long curve, not many tiny linear strips. The user's manual
        # EVIL bar-36 example demonstrates this independently of sharp flags.
        post_slam_curve = (isinstance(samples[0][1], list)
                           and len(samples) > 2
                           and span_error(samples, .5, .5) > 1e-5)
        end_sharp = len(samples[-2]) == 3 and samples[-2][2] == [1.0, 0.0]
        pointed_join = start_sharp or end_sharp
        if not (pointed_join or post_slam_curve):
            result.extend(p[:] for p in samples[:-1])
            continue
        if value(samples[0], True) == value(samples[-1]):
            result.extend(p[:] for p in samples[:-1])
            continue
        changed += 1
        stack = [(0, len(samples)-1)]
        while stack:
            start, stop = stack.pop()
            span = samples[start:stop+1]
            a, b = fit_span(span)
            if pointed_join and abs(a-b) < 0.01:
                # Some editors round near-equal control parameters before
                # choosing the corner renderer. Keep a visible separation so
                # an intended pointed join cannot collapse back to a square.
                if a == 0.5:
                    a = 0.499999
                delta = 0.01
                candidates = [min(1.0, a+delta), max(0.0, a-delta)]
                b = min((v for v in candidates if v != a),
                        key=lambda v: span_error(span, a, v))
            error = span_error(span, a, b)
            # Prefer the user's whole-curve form at slam exits. Local 1%
            # deviation is preferable to editor seams from tiny curve strips.
            allowed = max(tolerance, 0.01) if pointed_join or (start == 0 and isinstance(samples[0][1], list)) else tolerance
            if error <= allowed:
                result.append(span[0][:2]+[[a, b]])
                worst = max(worst, error)
            elif stop-start > 1:
                middle = (start+stop)//2
                # The editor shifts a post-slam curve start by the slam's
                # pixel height. Very short first curves can invert/collapse.
                # Keep at least 60 pulses (1/16 whole note) where the source
                # monotonic run allows it, without crossing a jump or turn.
                if start == 0 and isinstance(samples[0][1], list):
                    safe = next((i for i in range(1, stop+1)
                                 if samples[i][0]-samples[0][0] >= 60), stop)
                    middle = max(middle, safe)
                    if middle >= stop:
                        result.append(span[0][:2]+[[a, b]])
                        worst = max(worst, error)
                        continue
                stack.extend([(middle, stop), (start, middle)])
            else:
                raise ValueError('Sharp tolerance too small for stable nonzero curvature')
    result.append(points[-1][:])
    return result, worst, changed
