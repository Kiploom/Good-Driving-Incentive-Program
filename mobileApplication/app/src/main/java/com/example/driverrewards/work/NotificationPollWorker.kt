package com.example.driverrewards.work

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.example.driverrewards.MainActivity
import com.example.driverrewards.R
import com.example.driverrewards.network.NotificationItem
import com.example.driverrewards.network.NotificationService
import com.example.driverrewards.utils.SessionManager
import java.time.Instant

class NotificationPollWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    private val notificationService = NotificationService()
    private val sessionManager = SessionManager(appContext)

    override suspend fun doWork(): Result {
        return try {
            if (!sessionManager.isLoggedIn()) {
                return Result.success()
            }

            val lastSyncIso = sessionManager.getLastNotificationSync()
                ?: Instant.now().minusSeconds(INITIAL_WINDOW_SECONDS).toString()

            val response = notificationService.getNotifications(
                page = 1,
                pageSize = 10,
                unreadOnly = true,
                since = lastSyncIso
            )
            
            if (!response.success) {
                Result.retry()
            } else {
                val notifications = response.notifications.orEmpty()
                if (notifications.isNotEmpty()) {
                    ensureChannel()
                    notifications.forEach { pushSystemNotification(it) }
                }
                sessionManager.updateLastNotificationSync()
                Result.success()
            }
        } catch (ex: Exception) {
            android.util.Log.e("NotificationPollWorker", "Error in doWork", ex)
            Result.retry()
        }
    }

    private fun pushSystemNotification(notification: NotificationItem) {
        try {
            val intent = Intent(applicationContext, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                putExtra("navigate_to", "notifications")
            }
            
            val pendingIntent = PendingIntent.getActivity(
                applicationContext,
                0,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val builder = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_notifications)
                .setContentTitle(notification.title)
                .setContentText(notification.body.take(120))
                .setStyle(NotificationCompat.BigTextStyle().bigText(notification.body))
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)

            NotificationManagerCompat.from(applicationContext).notify(
                notification.id.hashCode(),
                builder.build()
            )
        } catch (ex: Exception) {
            android.util.Log.e("NotificationPollWorker", "Error creating notification", ex)
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val notificationManager =
                applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (notificationManager.getNotificationChannel(CHANNEL_ID) == null) {
                val channel = NotificationChannel(
                    CHANNEL_ID,
                    applicationContext.getString(R.string.title_notifications),
                    NotificationManager.IMPORTANCE_DEFAULT
                )
                notificationManager.createNotificationChannel(channel)
            }
        }
    }

    companion object {
        const val WORK_NAME = "driver_notifications_worker"
        private const val CHANNEL_ID = "driver_notifications"
        private const val INITIAL_WINDOW_SECONDS = 30L
    }
}

