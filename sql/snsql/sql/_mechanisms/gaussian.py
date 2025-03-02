import math
from opendp.mod import enable_features
from opendp.measurements import make_gaussian
from opendp.accuracy import gaussian_scale_to_accuracy
from opendp.typing import set_default_int_type
from .base import AdditiveNoiseMechanism, Mechanism
from .normal import _normal_dist_inv_cdf
import opendp.prelude as dp

class Gaussian(AdditiveNoiseMechanism):
    def __init__(
            self, epsilon, *ignore, delta, sensitivity=None, max_contrib=1, upper=None, lower=None, **kwargs
        ):
        super().__init__(
                epsilon,
                mechanism=Mechanism.gaussian,
                delta=delta,
                sensitivity=sensitivity,
                max_contrib=max_contrib,
                upper=upper,
                lower=lower
            )
        if delta <= 0.0:
            raise ValueError("Discrete gaussian mechanism delta must be greater than 0.0")
        self._compute_noise_scale()
    def _compute_noise_scale(self):
        if self.scale is not None:
            return
        bit_depth = self.bit_depth
        set_default_int_type(f"i{bit_depth}")
        lower = self.lower
        upper = self.upper
        max_contrib = self.max_contrib
        bounds = (float(math.floor(lower)), float(math.ceil(upper)))

        rough_scale = float(upper - lower) * max_contrib * math.sqrt(2.0 * math.log(1.25 / self.delta)) / self.epsilon
        if rough_scale > 10_000_000:
            raise ValueError(f"Noise scale is too large using epsilon={self.epsilon} and bounds ({lower}, {upper}) with {self.mechanism}.  Try preprocessing to reduce senstivity, or try different privacy parameters.")
        enable_features('floating-point', 'contrib')

        input_domain = dp.vector_domain(dp.atom_domain(T=float))
        input_metric = dp.symmetric_distance()

        bounded_sum = (input_domain, input_metric) >> dp.t.then_clamp(bounds=bounds) >> dp.t.then_sum()
        
        try:
            def make_adp_sum(scale):
                dp_sum = bounded_sum >> dp.m.then_gaussian(scale)
                adp_sum = dp.c.make_zCDP_to_approxDP(dp_sum)
                return dp.c.make_fix_delta(adp_sum, delta=self.delta)

            discovered_scale = dp.binary_search_param(
                lambda s: make_adp_sum(scale=s),
                d_in=max_contrib,
                d_out=(self.epsilon, self.delta))
        except Exception as e:
            raise ValueError(f"Unable to find appropriate noise scale for with {self.mechanism} with epsilon={self.epsilon} and bounds ({lower}, {upper}).  Try preprocessing to reduce senstivity, or try different privacy parameters.\n{e}")
        self.scale = discovered_scale
    @property
    def threshold(self):
        max_contrib = self.max_contrib
        delta = self.delta
        if delta == 0.0:
            raise ValueError("censor_dims requires delta to be > 0.0  Try delta=1/n*sqrt(n) where n is the number of individuals")
        thresh = 1 + self.scale * _normal_dist_inv_cdf((1 - delta / 2) ** (1 / max_contrib))
        return thresh
    def release(self, vals):
        enable_features('contrib')
        bit_depth = self.bit_depth
        set_default_int_type(f"i{bit_depth}")
        meas = make_gaussian(dp.atom_domain(T=float), dp.absolute_distance(T=float), self.scale)
        vals = [meas(float(v)) for v in vals]
        return vals
    def accuracy(self, alpha):
        bit_depth = self.bit_depth
        set_default_int_type(f"i{bit_depth}")
        return gaussian_scale_to_accuracy(self.scale, alpha)
        
