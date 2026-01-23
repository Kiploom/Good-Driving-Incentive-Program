package com.example.driverrewards.ui.catalog

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.graphics.Canvas
import android.graphics.Paint
import android.view.View
import android.view.ViewGroup
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random

class FavoriteParticleAnimation {
    
    companion object {
        fun animateFavorite(view: View, isFavoriting: Boolean) {
            val parent = view.parent as? ViewGroup ?: return
            
            // Get view position relative to parent
            val viewBounds = android.graphics.Rect()
            view.getHitRect(viewBounds)
            
            val particleView = ParticleAnimationView(view.context, isFavoriting)
            
            // Calculate center position relative to parent
            val centerX = viewBounds.left + viewBounds.width() / 2f
            val centerY = viewBounds.top + viewBounds.height() / 2f
            
            // Add particle view to parent, positioned to match parent coordinates
            val layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
            parent.addView(particleView, layoutParams)
            particleView.setCenterPosition(centerX, centerY)
            
            // Animate particles
            val animator = ValueAnimator.ofFloat(0f, 1f)
            animator.duration = 600
            animator.addUpdateListener { animation ->
                val progress = animation.animatedValue as Float
                particleView.updateParticles(progress)
            }
            animator.addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    parent.removeView(particleView)
                }
            })
            animator.start()
        }
    }
    
    private class ParticleAnimationView(
        context: android.content.Context,
        private val isFavoriting: Boolean
    ) : View(context) {
        
        private val particles = mutableListOf<Particle>()
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
        }
        
        private var centerX: Float = 0f
        private var centerY: Float = 0f
        
        init {
            // Make view transparent and non-interactive
            setBackgroundColor(android.graphics.Color.TRANSPARENT)
            isClickable = false
            isFocusable = false
            
            // Create 15-20 particles
            repeat(18) {
                val angle = (360 / 18 * it + Random.nextInt(-10, 10)) * Math.PI / 180
                val speed = 150f + Random.nextFloat() * 100f
                val size = 4f + Random.nextFloat() * 4f
                
                particles.add(
                    Particle(
                        angle = angle,
                        speed = speed,
                        size = size,
                        startX = 0f,
                        startY = 0f
                    )
                )
            }
        }
        
        fun setCenterPosition(x: Float, y: Float) {
            centerX = x
            centerY = y
        }
        
        fun updateParticles(progress: Float) {
            particles.forEach { particle ->
                val distance = particle.speed * progress
                particle.x = centerX + cos(particle.angle).toFloat() * distance
                particle.y = centerY + sin(particle.angle).toFloat() * distance
                particle.alpha = (1f - progress) * 255f
            }
            invalidate()
        }
        
        override fun onTouchEvent(event: android.view.MotionEvent?): Boolean {
            // Don't intercept touch events - let them pass through
            return false
        }
        
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            
            particles.forEach { particle ->
                val color = if (isFavoriting) {
                    // Red/pink gradient for favoriting
                    android.graphics.Color.rgb(
                        (255 - (particle.alpha * 0.3).toInt()).coerceIn(200, 255),
                        (50 + particle.alpha * 0.2).toInt().coerceIn(50, 100),
                        (50 + particle.alpha * 0.2).toInt().coerceIn(50, 100)
                    )
                } else {
                    // Gray for unfavoriting
                    android.graphics.Color.rgb(
                        (128 - particle.alpha * 0.3).toInt().coerceIn(100, 128),
                        (128 - particle.alpha * 0.3).toInt().coerceIn(100, 128),
                        (128 - particle.alpha * 0.3).toInt().coerceIn(100, 128)
                    )
                }
                
                paint.color = color
                paint.alpha = particle.alpha.toInt()
                canvas.drawCircle(particle.x, particle.y, particle.size, paint)
            }
        }
        
        private data class Particle(
            val angle: Double,
            val speed: Float,
            val size: Float,
            var x: Float = 0f,
            var y: Float = 0f,
            var alpha: Float = 255f,
            var startX: Float,
            var startY: Float
        )
    }
}

