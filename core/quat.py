"""Quaternion helpers on numpy arrays (w, x, y, z), last axis of size 4. No bpy.

Used where a whole motion is processed at once (backends, bulk F-curve writing). numpy ships with Blender.
"""
import numpy as np


def multiply(a, b):
    """Hamilton product a * b (rotation b, then a), broadcast over the leading axes."""
    aw, ax, ay, az = np.moveaxis(np.asarray(a, dtype=np.float64), -1, 0)
    bw, bx, by, bz = np.moveaxis(np.asarray(b, dtype=np.float64), -1, 0)
    return np.stack((
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ), axis=-1)


def conjugate(q):
    """Inverse of unit quaternions."""
    q = np.asarray(q, dtype=np.float64)
    return q * np.array((1.0, -1.0, -1.0, -1.0))


def normalize(q):
    q = np.asarray(q, dtype=np.float64)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def rotate(q, v):
    """Rotate vectors v (..., 3) by unit quaternions q (..., 4)."""
    v = np.asarray(v, dtype=np.float64)
    pure = np.concatenate((np.zeros(v.shape[:-1] + (1,)), v), axis=-1)
    return multiply(multiply(q, pure), conjugate(q))[..., 1:]


def from_matrix(m):
    """Unit quaternions from rotation matrices (..., 3, 3), with w >= 0."""
    m = np.asarray(m, dtype=np.float64)
    m00, m01, m02 = m[..., 0, 0], m[..., 0, 1], m[..., 0, 2]
    m10, m11, m12 = m[..., 1, 0], m[..., 1, 1], m[..., 1, 2]
    m20, m21, m22 = m[..., 2, 0], m[..., 2, 1], m[..., 2, 2]
    # Shepperd: build the quaternion from its largest component, for precision near 180 degrees
    candidates = np.stack((
        np.stack((1.0 + m00 + m11 + m22, m21 - m12, m02 - m20, m10 - m01), axis=-1),
        np.stack((m21 - m12, 1.0 + m00 - m11 - m22, m01 + m10, m02 + m20), axis=-1),
        np.stack((m02 - m20, m01 + m10, 1.0 - m00 + m11 - m22, m12 + m21), axis=-1),
        np.stack((m10 - m01, m02 + m20, m12 + m21, 1.0 - m00 - m11 + m22), axis=-1),
    ), axis=-2)
    diagonal = np.stack((m00 + m11 + m22, m00, m11, m22), axis=-1)
    best = np.argmax(diagonal, axis=-1)
    q = np.take_along_axis(candidates, best[..., None, None], axis=-2)[..., 0, :]
    q = normalize(q)
    return np.where(q[..., :1] < 0.0, -q, q)


def to_matrix(q):
    """Rotation matrices (..., 3, 3) from unit quaternions."""
    w, x, y, z = np.moveaxis(normalize(q), -1, 0)
    return np.stack((
        np.stack((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)), axis=-1),
        np.stack((2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)), axis=-1),
        np.stack((2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)), axis=-1),
    ), axis=-2)


def from_axis_angle(v):
    """Unit quaternions from rotation vectors (..., 3): axis * angle in radians."""
    v = np.asarray(v, dtype=np.float64)
    angle = np.linalg.norm(v, axis=-1, keepdims=True)
    half = 0.5 * angle
    # sin(half) / angle -> 0.5 when the angle goes to 0
    scale = np.where(angle > 1e-12, np.sin(half) / np.where(angle > 1e-12, angle, 1.0), 0.5)
    return np.concatenate((np.cos(half), v * scale), axis=-1)


def to_axis_angle(q):
    """Rotation vectors (..., 3), axis * angle with the angle in [0, pi]."""
    q = normalize(q)
    q = np.where(q[..., :1] < 0.0, -q, q)
    sin_half = np.linalg.norm(q[..., 1:], axis=-1, keepdims=True)
    angle = 2.0 * np.arctan2(sin_half, q[..., :1])
    scale = np.where(sin_half > 1e-12, angle / np.where(sin_half > 1e-12, sin_half, 1.0), 2.0)
    return q[..., 1:] * scale


def slerp(a, b, t):
    """Spherical interpolation from a to b, broadcast over the leading axes; t in [0, 1] broadcasts too.
    Takes the short way (b is flipped when a . b < 0)."""
    a = normalize(a)
    b = normalize(b)
    t = np.asarray(t, dtype=np.float64)
    dot = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(dot < 0.0, -b, b)
    dot = np.abs(dot)
    theta = np.arccos(np.clip(dot, -1.0, 1.0))
    sin_theta = np.sin(theta)
    close = sin_theta < 1e-6
    safe = np.where(close, 1.0, sin_theta)
    wa = np.where(close, 1.0 - t, np.sin((1.0 - t) * theta) / safe)
    wb = np.where(close, t, np.sin(t * theta) / safe)
    return normalize(wa * a + wb * b)


def make_continuous(q, axis=0):
    """Flip signs along `axis` (frames) so consecutive quaternions stay in the same hemisphere.
    q and -q are the same rotation, but interpolating between them spins the long way round."""
    q = np.moveaxis(np.array(q, dtype=np.float64), axis, 0)
    if len(q) > 1:
        dots = np.sum(q[1:] * q[:-1], axis=-1)
        flips = np.cumprod(np.where(dots < 0.0, -1.0, 1.0), axis=0)
        q[1:] *= flips[..., None]
    return np.moveaxis(q, 0, axis)
